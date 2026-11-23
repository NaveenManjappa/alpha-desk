import { TestBed } from '@angular/core/testing';
import { Observable, of, Subject, throwError } from 'rxjs';

import { ApiClient } from '../api/api-client';
import { ChatStream, ChatStreamError, ChatStreamFailure } from '../api/chat-stream';
import { ChatEvent } from '../models/chat-events';
import { ChatRequest } from '../models/chat-request';
import { Thread } from '../models/thread';
import { ANSWER, ANSWER_MESSAGE, USAGE } from '../testing/samples';
import { ChatSession } from './chat-session';

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
  let runs: FakeRun[];

  beforeEach(() => {
    localStorage.clear();
    getThread.mockReset();
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
});
