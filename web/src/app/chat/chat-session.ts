import { computed, inject, Service, signal } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';

import { ApiClient } from '../api/api-client';
import { ChatStream, ChatStreamError, ChatStreamFailure } from '../api/chat-stream';
import { ChatEvent } from '../models/chat-events';
import { ThreadMessage, ThreadSummary } from '../models/thread';
import { Conversations } from './conversations';
import { ThreadIdStorage } from './thread-id-storage';

const FAILURE_MESSAGES: Record<ChatStreamFailure, string> = {
  unreachable: 'The research desk could not be reached. Check that the API is running.',
  rejected: 'The research desk did not accept that message. It may be too long.',
  lost: 'The connection was lost before the answer arrived. Please ask again.',
};

/**
 * The state of the chat, all in one place. Components read its signals and call its
 * methods; only this class changes it.
 */
@Service()
export class ChatSession {
  private readonly api = inject(ApiClient);
  private readonly stream = inject(ChatStream);
  private readonly storage = inject(ThreadIdStorage);
  private readonly conversations = inject(Conversations);

  private readonly _threadId = signal(this.storage.read());

  /**
   * The conversation to fetch from the API. Undefined when there is none to fetch. An object,
   * so that opening a conversation is a new request each time, even for the same ID.
   */
  private readonly saved = signal(savedThread(this._threadId()));

  /** Earlier messages. A resource, as this is a read: it runs when there is an ID to fetch. */
  private readonly history = rxResource({
    params: () => this.saved(),
    stream: ({ params: { threadId } }) => this.api.getThread(threadId),
  });

  /** The conversation the next message belongs to. Undefined until the first message. */
  readonly threadId = this._threadId.asReadonly();

  /** Messages added since the page opened. Kept apart from the history they follow. */
  private readonly added = signal<ThreadMessage[]>([]);

  /** The run in progress, if any. Aborting it stops the run. */
  private readonly activeRun = signal<AbortController | undefined>(undefined);

  private readonly _statusLines = signal<string[]>([]);
  private readonly _failure = signal<string | undefined>(undefined);

  /** The whole conversation, oldest first. */
  readonly messages = computed<ThreadMessage[]>(() => [
    ...(this.history.hasValue() ? this.history.value().messages : []),
    ...this.added(),
  ]);

  /** What the current run has done so far. The last line is what it is doing now. */
  readonly statusLines = this._statusLines.asReadonly();

  /** Why the last run failed, ready to show. Undefined if it did not. */
  readonly failure = this._failure.asReadonly();

  readonly running = computed(() => this.activeRun() !== undefined);
  readonly loadingHistory = this.history.isLoading;
  readonly historyFailed = computed(() => this.history.error() !== undefined);

  /**
   * Not while the history is missing: a message sent then would be shown out of order. And
   * not while the conversation is being deleted: the run would write it back.
   */
  readonly canSend = computed(
    () =>
      !this.running() &&
      !this.loadingHistory() &&
      !this.historyFailed() &&
      !this.conversations.deleting().has(this.threadId() ?? ''),
  );

  /** Ask a question. Does nothing while `canSend` is false. */
  async send(message: string): Promise<void> {
    if (!this.canSend()) {
      return;
    }
    const run = new AbortController();
    this.activeRun.set(run);
    this._failure.set(undefined);
    this.add({ type: 'question', text: message });
    const request = { message, thread_id: this.currentThreadId() };
    let listed = false;

    try {
      for await (const event of this.stream.send(request, run.signal)) {
        if (run.signal.aborted) {
          return;
        }
        if (!listed) {
          // The API lists the conversation before it sends anything, so it is there by now.
          listed = true;
          this.conversations.refresh();
        }
        this.apply(event);
      }
    } catch (error) {
      if (!(error instanceof ChatStreamError)) {
        throw error; // A bug, not a failed connection. Angular's error handler reports it.
      }
      if (!run.signal.aborted) {
        this._failure.set(FAILURE_MESSAGES[error.reason]);
      }
    } finally {
      // In another conversation a newer run may be active. That one is not ours to end.
      if (this.activeRun() === run) {
        this.endRun();
      }
      this.conversations.refresh();
    }
  }

  /** Stop any run and start again with no messages. The old thread stays in the API. */
  startNewConversation(): void {
    this.storage.clear();
    this.switchTo(undefined);
  }

  /** Stop any run and show an earlier conversation. Does nothing if it is the open one. */
  openConversation(threadId: string): void {
    if (threadId === this.threadId()) {
      return;
    }
    this.storage.save(threadId);
    this.switchTo(threadId);
  }

  /** Not the open conversation while its answer is running: the run would write it back. */
  canDelete(threadId: string): boolean {
    return !(this.running() && threadId === this.threadId());
  }

  /** Delete a conversation for good. Deleting the open one starts a new conversation. */
  async deleteConversation(thread: ThreadSummary): Promise<boolean> {
    if (!this.canDelete(thread.thread_id)) {
      return false;
    }
    const deleted = await this.conversations.delete(thread);
    // Asked now, not before: the user may have opened another one in the meantime.
    if (deleted && thread.thread_id === this.threadId()) {
      this.startNewConversation();
    }
    return deleted;
  }

  /** Try again to fetch the history after it failed. */
  reloadHistory(): void {
    this.history.reload();
  }

  private apply(event: ChatEvent): void {
    switch (event.type) {
      case 'status':
        this._statusLines.update((lines) => [...lines, event.message]);
        break;
      case 'final':
        this.add({ type: 'answer', answer: event.answer, usage: event.usage });
        break;
      case 'error':
        this._failure.set(event.message);
        break;
      case 'token':
        // Not shown. Text on the way to an answer has not been through the grounding check.
        break;
    }
  }

  private add(message: ThreadMessage): void {
    this.added.update((messages) => [...messages, message]);
  }

  private switchTo(threadId: string | undefined): void {
    this.activeRun()?.abort();
    this.endRun();
    this._threadId.set(threadId);
    this.saved.set(savedThread(threadId));
    this.added.set([]);
    this._failure.set(undefined);
  }

  private endRun(): void {
    this.activeRun.set(undefined);
    this._statusLines.set([]);
  }

  /** The conversation's ID, made and kept on its first message. */
  private currentThreadId(): string {
    let threadId = this.threadId();
    if (threadId === undefined) {
      threadId = crypto.randomUUID();
      this._threadId.set(threadId);
      this.storage.save(threadId);
    }
    return threadId;
  }
}

function savedThread(threadId: string | undefined): { threadId: string } | undefined {
  return threadId === undefined ? undefined : { threadId };
}
