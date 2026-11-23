import { computed, inject, Service, signal } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';

import { ApiClient } from '../api/api-client';
import { ChatStream, ChatStreamError, ChatStreamFailure } from '../api/chat-stream';
import { ChatEvent } from '../models/chat-events';
import { ThreadMessage } from '../models/thread';
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

  /** The conversation to fetch from the API. Undefined when there is none to fetch. */
  private readonly savedThreadId = signal(this.storage.read());

  /** Earlier messages. A resource, as this is a read: it runs when there is an ID to fetch. */
  private readonly history = rxResource({
    params: () => this.savedThreadId(),
    stream: ({ params: threadId }) => this.api.getThread(threadId),
  });

  /** The conversation the next message belongs to. Undefined until the first message. */
  private threadId = this.savedThreadId();

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

  /** Not while the history is missing: a message sent then would be shown out of order. */
  readonly canSend = computed(
    () => !this.running() && !this.loadingHistory() && !this.historyFailed(),
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

    try {
      for await (const event of this.stream.send(request, run.signal)) {
        if (run.signal.aborted) {
          return;
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
      // After "New conversation" a newer run may be active. That one is not ours to end.
      if (this.activeRun() === run) {
        this.endRun();
      }
    }
  }

  /** Stop any run and start again with no messages. The old thread stays in the API. */
  startNewConversation(): void {
    this.activeRun()?.abort();
    this.endRun();
    this.storage.clear();
    this.threadId = undefined;
    this.savedThreadId.set(undefined);
    this.added.set([]);
    this._failure.set(undefined);
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

  private endRun(): void {
    this.activeRun.set(undefined);
    this._statusLines.set([]);
  }

  /** The conversation's ID, made and kept on its first message. */
  private currentThreadId(): string {
    if (this.threadId === undefined) {
      this.threadId = crypto.randomUUID();
      this.storage.save(this.threadId);
    }
    return this.threadId;
  }
}
