import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Observable, of, Subject, throwError } from 'rxjs';

import { ApiClient } from '../api/api-client';
import { ChatStream, ChatStreamError, ChatStreamFailure } from '../api/chat-stream';
import { ChatEvent } from '../models/chat-events';
import { ChatRequest } from '../models/chat-request';
import { Thread, ThreadSummary } from '../models/thread';
import { ANSWER, ANSWER_MESSAGE, APPLE_THREAD, NVIDIA_THREAD, USAGE } from '../testing/samples';
import { ChatSession } from './chat-session';
import { Conversations } from './conversations';

const STATUS: ChatEvent = { type: 'status', tool: 'get_quote', message: 'Getting the price' };
const FINAL: ChatEvent = { type: 'final', answer: ANSWER, usage: USAGE };
const STORAGE_KEY = 'alphadesk.thread-id';

/** A run the test drives by hand: what it yields, and how it ends. */
class FakeRun {
  private readonly pending: (() => void)[] = [];
  private readonly steps: (ChatEvent | Error | 'end')[] = [];

  constructor(
    readonly request: ChatRequest,
    readonly signal: AbortSignal | undefined,
  ) {}

  /** Let the session take in one step, all its effects included. */
  async next(step: ChatEvent | Error | 'end'): Promise<void> {
    this.steps.push(step);
    this.pending.shift()?.();
    await new Promise((resolve) => setTimeout(resolve));
  }

  async *events(): AsyncGenerator<ChatEvent> {
    while (true) {
      if (this.steps.length === 0) {
        await new Promise<void>((resolve) => this.pending.push(resolve));
      }
      const step = this.steps.shift();
      if (step === undefined || step === 'end') {
        return;
      }
      if (step instanceof Error) {
        throw step;
      }
      yield step;
    }
  }
}

describe('ChatSession', () => {
  const getThread = vi.fn<(id: string) => Observable<Thread>>();
  const conversations = {
    deleting: signal<ReadonlySet<string>>(new Set()),
    refresh: vi.fn(),
    delete: vi.fn<(thread: ThreadSummary) => Promise<boolean>>(),
  };
  let runs: FakeRun[];

  beforeEach(() => {
    localStorage.clear();
    getThread.mockReset();
    conversations.refresh.mockReset();
    conversations.delete.mockReset();
    conversations.deleting.set(new Set());
    runs = [];
    const send = (request: ChatRequest, signal?: AbortSignal) => {
      const run = new FakeRun(request, signal);
      runs.push(run);
      return run.events();
    };
    TestBed.configureTestingModule({
      providers: [
        { provide: ApiClient, useValue: { getThread } },
        { provide: ChatStream, useValue: { send } },
        { provide: Conversations, useValue: conversations },
      ],
    });
  });

  afterEach(() => localStorage.clear());

  function open(): ChatSession {
    const session = TestBed.inject(ChatSession);
    TestBed.tick();
    return session;
  }

  function types(session: ChatSession): string[] {
    return session.messages().map((message) => message.type);
  }

  it('starts empty, without asking the API for anything', () => {
    const session = open();

    expect(session.messages()).toEqual([]);
    expect(session.canSend()).toBe(true);
    expect(getThread).not.toHaveBeenCalled();
  });

  describe('a run', () => {
    it('shows the question at once, then status lines, then the answer', async () => {
      const session = open();
      void session.send('How is Apple doing?');

      expect(session.messages()).toEqual([{ type: 'question', text: 'How is Apple doing?' }]);
      expect(session.running()).toBe(true);
      expect(session.canSend()).toBe(false);

      await runs[0].next(STATUS);
      expect(session.statusLines()).toEqual(['Getting the price']);

      await runs[0].next(FINAL);
      await runs[0].next('end');
      expect(session.messages().at(-1)).toEqual(ANSWER_MESSAGE);
      expect(session.running()).toBe(false);
      expect(session.statusLines()).toEqual([]);
      expect(session.failure()).toBeUndefined();
    });

    it('does not show text that has not been through the grounding check', async () => {
      const session = open();
      void session.send('Hi');

      await runs[0].next({ type: 'token', text: 'Revenue was 1 trillion' });

      expect(types(session)).toEqual(['question']);
      expect(session.statusLines()).toEqual([]);
    });

    it('ignores a second message while one is running', async () => {
      const session = open();
      void session.send('First');
      await session.send('Second');

      expect(runs).toHaveLength(1);
      expect(types(session)).toEqual(['question']);
    });

    it('shows the message of an error event, and clears it on the next try', async () => {
      const session = open();
      void session.send('First');
      await runs[0].next(STATUS);
      await runs[0].next({ type: 'error', message: 'Try one company at a time.' });
      await runs[0].next('end');

      expect(session.failure()).toBe('Try one company at a time.');
      expect(session.running()).toBe(false);
      expect(session.statusLines()).toEqual([]);

      void session.send('Second');
      expect(session.failure()).toBeUndefined();
    });

    it.each<[ChatStreamFailure, string]>([
      ['unreachable', 'could not be reached'],
      ['rejected', 'did not accept'],
      ['lost', 'connection was lost'],
    ])('explains a stream that is %s, and recovers on the next try', async (reason, text) => {
      const session = open();
      void session.send('First');
      await runs[0].next(new ChatStreamError(reason));

      expect(session.failure()).toContain(text);
      expect(session.canSend()).toBe(true);

      void session.send('Second');
      await runs[1].next(FINAL);
      await runs[1].next('end');

      expect(session.failure()).toBeUndefined();
      expect(types(session)).toEqual(['question', 'question', 'answer']);
      expect(runs[1].request.thread_id).toBe(runs[0].request.thread_id);
    });
  });

  describe('the thread ID', () => {
    it('is made on the first message, kept in the browser and reused', async () => {
      const session = open();
      expect(localStorage.getItem(STORAGE_KEY)).toBeNull();

      void session.send('How is Apple doing?');
      await runs[0].next(FINAL);
      await runs[0].next('end');
      void session.send('And its revenue?');

      const id = runs[0].request.thread_id;
      expect(id).toMatch(/^[A-Za-z0-9_-]{1,64}$/); // What the API accepts.
      expect(localStorage.getItem(STORAGE_KEY)).toBe(id);
      expect(runs[1].request.thread_id).toBe(id);
    });

    it('works without browser storage', () => {
      const blocked = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
        throw new DOMException('blocked', 'SecurityError');
      });

      expect(open().canSend()).toBe(true);

      blocked.mockRestore();
    });
  });

  describe('after a reload', () => {
    beforeEach(() => localStorage.setItem(STORAGE_KEY, 'apple'));

    const thread: Thread = {
      thread_id: 'apple',
      messages: [{ type: 'question', text: 'How is Apple doing?' }, ANSWER_MESSAGE],
    };

    it('gets the conversation from the API and continues it', async () => {
      const reply = new Subject<Thread>();
      getThread.mockReturnValue(reply);
      const session = open();

      expect(getThread).toHaveBeenCalledWith('apple');
      expect(session.loadingHistory()).toBe(true);
      expect(session.canSend()).toBe(false);

      reply.next(thread);
      reply.complete();
      await vi.waitFor(() => expect(session.messages()).toEqual(thread.messages));

      void session.send('And its revenue?');
      expect(runs[0].request.thread_id).toBe('apple');
      expect(types(session)).toEqual(['question', 'answer', 'question']);
    });

    it('says so when the conversation cannot be fetched, and can try again', async () => {
      getThread.mockReturnValueOnce(throwError(() => new Error('no connection')));
      getThread.mockReturnValueOnce(of(thread));
      const session = open();

      expect(session.historyFailed()).toBe(true);
      expect(session.canSend()).toBe(false);

      session.reloadHistory();
      TestBed.tick();

      expect(session.historyFailed()).toBe(false);
      expect(session.messages()).toEqual(thread.messages);
    });
  });

  describe('a new conversation', () => {
    it('forgets the old one, in the page and in the browser', async () => {
      localStorage.setItem(STORAGE_KEY, 'apple');
      getThread.mockReturnValue(
        of({ thread_id: 'apple', messages: [{ type: 'question', text: 'Old' }] }),
      );
      const session = open();
      expect(types(session)).toEqual(['question']);

      session.startNewConversation();
      TestBed.tick();

      expect(session.messages()).toEqual([]);
      expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
      void session.send('New');
      expect(runs[0].request.thread_id).not.toBe('apple');
      expect(types(session)).toEqual(['question']);
    });

    it('stops the run in progress, whose late events change nothing', async () => {
      const session = open();
      void session.send('Old question');
      session.startNewConversation();
      expect(runs[0].signal?.aborted).toBe(true);

      void session.send('New question');
      await runs[0].next(FINAL);

      expect(types(session)).toEqual(['question']);
      expect(session.running()).toBe(true);
      expect(session.failure()).toBeUndefined();
    });
  });

  describe('opening another conversation', () => {
    const apple: Thread = {
      thread_id: 'apple',
      messages: [{ type: 'question', text: 'How is Apple doing?' }, ANSWER_MESSAGE],
    };
    const nvidia: Thread = {
      thread_id: 'nvidia',
      messages: [{ type: 'question', text: 'How is Nvidia doing?' }],
    };

    beforeEach(() =>
      getThread.mockImplementation((id) => of(id === 'apple' ? apple : { ...nvidia })),
    );

    it('shows it, continues it, and finds it again after a reload', () => {
      const session = open();
      session.openConversation('apple');
      TestBed.tick();

      expect(session.threadId()).toBe('apple');
      expect(session.messages()).toEqual(apple.messages);
      expect(localStorage.getItem(STORAGE_KEY)).toBe('apple');

      void session.send('And its revenue?');
      expect(runs[0].request.thread_id).toBe('apple');
    });

    it('stops the run in progress, and nothing from it appears', async () => {
      const session = open();
      void session.send('Slow question');
      await runs[0].next(STATUS);

      session.openConversation('apple');
      TestBed.tick();
      expect(runs[0].signal?.aborted).toBe(true);
      expect(session.running()).toBe(false);
      expect(session.statusLines()).toEqual([]);

      await runs[0].next(FINAL);
      await runs[0].next(new ChatStreamError('lost'));
      expect(session.messages()).toEqual(apple.messages);
      expect(session.failure()).toBeUndefined();
    });

    it('does nothing for the one that is already open, even during its run', async () => {
      const session = open();
      session.openConversation('apple');
      TestBed.tick();
      void session.send('And its revenue?');

      session.openConversation('apple');
      TestBed.tick();

      expect(session.running()).toBe(true);
      expect(types(session)).toEqual(['question', 'answer', 'question']);
      expect(getThread).toHaveBeenCalledOnce();
    });

    it('fetches again when switching away and back, however fast', () => {
      const session = open();
      session.openConversation('apple');
      TestBed.tick();

      session.openConversation('nvidia');
      session.openConversation('apple'); // Nothing has run in between.
      TestBed.tick();

      expect(getThread).toHaveBeenCalledTimes(2);
      expect(session.messages()).toEqual(apple.messages);
    });

    it('clears a failure left by the conversation before', async () => {
      const session = open();
      void session.send('First');
      await runs[0].next(new ChatStreamError('lost'));

      session.openConversation('apple');

      expect(session.failure()).toBeUndefined();
    });
  });

  describe('the list of conversations', () => {
    it('refreshes on the first event of a turn, and again at its end', async () => {
      const session = open();
      void session.send('How is Apple doing?');
      expect(conversations.refresh).not.toHaveBeenCalled(); // Not listed yet.

      await runs[0].next(STATUS);
      expect(conversations.refresh).toHaveBeenCalledTimes(1);

      await runs[0].next(STATUS);
      await runs[0].next(FINAL);
      expect(conversations.refresh).toHaveBeenCalledTimes(1);

      await runs[0].next('end');
      expect(conversations.refresh).toHaveBeenCalledTimes(2);
    });

    it('refreshes when a turn fails too', async () => {
      const session = open();
      void session.send('How is Apple doing?');
      await runs[0].next(new ChatStreamError('lost'));

      expect(conversations.refresh).toHaveBeenCalledOnce();
    });
  });

  describe('deleting a conversation', () => {
    beforeEach(() => {
      localStorage.setItem(STORAGE_KEY, 'apple');
      getThread.mockReturnValue(
        of({ thread_id: 'apple', messages: [{ type: 'question', text: 'Apple?' }] }),
      );
    });

    it('starts a new conversation when it was the open one', async () => {
      conversations.delete.mockResolvedValue(true);
      const session = open();

      await expect(session.deleteConversation(APPLE_THREAD)).resolves.toBe(true);
      TestBed.tick();

      expect(session.messages()).toEqual([]);
      expect(session.threadId()).toBeUndefined();
      expect(localStorage.getItem(STORAGE_KEY)).toBeNull();
    });

    it('leaves the open one alone when it was another', async () => {
      conversations.delete.mockResolvedValue(true);
      const session = open();

      await session.deleteConversation(NVIDIA_THREAD);
      TestBed.tick();

      expect(session.threadId()).toBe('apple');
      expect(types(session)).toEqual(['question']);
    });

    it('leaves the open one on the page when the delete failed', async () => {
      conversations.delete.mockResolvedValue(false);
      const session = open();

      await expect(session.deleteConversation(APPLE_THREAD)).resolves.toBe(false);

      expect(session.threadId()).toBe('apple');
      expect(localStorage.getItem(STORAGE_KEY)).toBe('apple');
    });

    it('is not possible for the open one while its answer is running', async () => {
      const session = open();
      void session.send('And its revenue?');

      expect(session.canDelete('apple')).toBe(false);
      expect(session.canDelete('nvidia')).toBe(true);
      await expect(session.deleteConversation(APPLE_THREAD)).resolves.toBe(false);
      expect(conversations.delete).not.toHaveBeenCalled();
    });

    it('holds back messages to it until it is done', () => {
      const session = open();
      expect(session.canSend()).toBe(true);

      conversations.deleting.set(new Set(['apple']));

      expect(session.canSend()).toBe(false);
    });
  });
});
