import { HttpErrorResponse } from '@angular/common/http';
import { TestBed } from '@angular/core/testing';
import { Observable, of, Subject, throwError } from 'rxjs';

import { ApiClient } from '../api/api-client';
import { ThreadSummary } from '../models/thread';
import { APPLE_THREAD as APPLE, NVIDIA_THREAD as NVIDIA } from '../testing/samples';
import { Conversations } from './conversations';

const DOWN = throwError(() => new HttpErrorResponse({ status: 503 }));

describe('Conversations', () => {
  const listThreads = vi.fn<() => Observable<ThreadSummary[]>>();
  const deleteThread = vi.fn<(id: string) => Observable<void>>();

  beforeEach(() => {
    listThreads.mockReset();
    deleteThread.mockReset();
    TestBed.configureTestingModule({
      providers: [{ provide: ApiClient, useValue: { listThreads, deleteThread } }],
    });
  });

  function open(): Conversations {
    const conversations = TestBed.inject(Conversations);
    settle(conversations);
    return conversations;
  }

  /** Let a refresh start, and read the list as the page would. */
  function settle(conversations: Conversations): void {
    TestBed.tick();
    conversations.list();
  }

  it('has no list until one loads, then shows what the API sent', async () => {
    const reply = new Subject<ThreadSummary[]>();
    listThreads.mockReturnValue(reply);
    const conversations = open();
    expect(conversations.list()).toBeUndefined();

    reply.next([NVIDIA, APPLE]);
    reply.complete();

    await vi.waitFor(() => expect(conversations.list()).toEqual([NVIDIA, APPLE]));
  });

  it('keeps the list on screen while it refreshes, and after a refresh fails', async () => {
    const second = new Subject<ThreadSummary[]>();
    listThreads.mockReturnValueOnce(of([APPLE])).mockReturnValueOnce(second);
    const conversations = open();

    conversations.refresh();
    settle(conversations);
    expect(conversations.list()).toEqual([APPLE]);

    second.error(new HttpErrorResponse({ status: 503 }));
    await vi.waitFor(() => expect(conversations.failed()).toBe(true));
    expect(conversations.list()).toEqual([APPLE]);
  });

  it('says so when it cannot load, and recovers on the next try', () => {
    listThreads.mockReturnValueOnce(DOWN).mockReturnValueOnce(of([APPLE]));
    const conversations = open();
    expect(conversations.failed()).toBe(true);
    expect(conversations.list()).toBeUndefined();

    conversations.refresh();
    settle(conversations);

    expect(conversations.failed()).toBe(false);
    expect(conversations.list()).toEqual([APPLE]);
  });

  it('drops a load that a newer refresh has overtaken', () => {
    const slow = new Subject<ThreadSummary[]>();
    listThreads.mockReturnValueOnce(slow).mockReturnValueOnce(of([NVIDIA, APPLE]));
    const conversations = open();

    conversations.refresh();
    settle(conversations);
    expect(slow.observed).toBe(false);
    slow.next([APPLE]);

    expect(conversations.list()).toEqual([NVIDIA, APPLE]);
  });

  describe('delete', () => {
    it('takes the conversation off the list, even if the refresh fails', async () => {
      listThreads.mockReturnValueOnce(of([NVIDIA, APPLE])).mockReturnValueOnce(DOWN);
      deleteThread.mockReturnValue(of(undefined));
      const conversations = open();

      await expect(conversations.delete(APPLE)).resolves.toBe(true);
      settle(conversations);

      expect(deleteThread).toHaveBeenCalledWith('apple');
      expect(conversations.list()).toEqual([NVIDIA]);
      expect(conversations.deleteFailure()).toBeUndefined();
    });

    it('is in progress until the API has answered', async () => {
      listThreads.mockReturnValue(of([APPLE]));
      const reply = new Subject<void>();
      deleteThread.mockReturnValue(reply);
      const conversations = open();

      const done = conversations.delete(APPLE);
      expect([...conversations.deleting()]).toEqual(['apple']);

      reply.next();
      await done;
      expect(conversations.deleting().size).toBe(0);
    });

    it('keeps the conversation and says so when it fails, until the next try', async () => {
      listThreads.mockReturnValue(of([NVIDIA, APPLE]));
      deleteThread.mockReturnValueOnce(DOWN).mockReturnValueOnce(of(undefined));
      const conversations = open();

      await expect(conversations.delete(APPLE)).resolves.toBe(false);

      expect(conversations.list()).toEqual([NVIDIA, APPLE]);
      expect(conversations.deleteFailure()).toContain(APPLE.title);
      expect(conversations.deleting().size).toBe(0);

      await conversations.delete(APPLE);
      expect(conversations.deleteFailure()).toBeUndefined();
    });
  });
});
