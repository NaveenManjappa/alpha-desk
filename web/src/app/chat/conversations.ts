import { HttpErrorResponse } from '@angular/common/http';
import { computed, inject, linkedSignal, Service, signal } from '@angular/core';
import { rxResource } from '@angular/core/rxjs-interop';
import { firstValueFrom } from 'rxjs';

import { ApiClient } from '../api/api-client';
import { ThreadSummary } from '../models/thread';

/** The list of earlier conversations. Which one is open is `ChatSession`'s to know. */
@Service()
export class Conversations {
  private readonly api = inject(ApiClient);

  /**
   * Counts the refreshes. The list reloads when it changes, rather than by the resource's
   * `reload()`, which does nothing while a load is in progress. That load may have started
   * before the change the refresh is for. A change of params cancels it and starts again.
   */
  private readonly version = signal(0);

  private readonly loaded = rxResource({
    params: () => ({ version: this.version() }),
    stream: () => this.api.listThreads(),
  });

  /** The last list that loaded. It stays while a newer one loads, or fails to. */
  private readonly known = linkedSignal<
    readonly ThreadSummary[] | undefined,
    readonly ThreadSummary[] | undefined
  >({
    source: () => (this.loaded.hasValue() ? this.loaded.value() : undefined),
    computation: (loaded, previous) => loaded ?? previous?.value,
  });

  private readonly _deleting = signal<ReadonlySet<string>>(new Set());
  private readonly _deleteFailure = signal<string | undefined>(undefined);

  /** Newest first. Undefined until a list has loaded. */
  readonly list = this.known.asReadonly();

  readonly failed = computed(() => this.loaded.error() !== undefined);

  /** The IDs of the conversations being deleted now. */
  readonly deleting = this._deleting.asReadonly();

  /** Why the last delete failed, ready to show. Undefined if it did not. */
  readonly deleteFailure = this._deleteFailure.asReadonly();

  /** Fetch the list again. */
  refresh(): void {
    this.version.update((version) => version + 1);
  }

  /** Delete a conversation for good. Returns whether it is gone. It stays listed if not. */
  async delete({ thread_id: threadId, title }: ThreadSummary): Promise<boolean> {
    this._deleteFailure.set(undefined);
    this._deleting.update((ids) => new Set([...ids, threadId]));
    try {
      await firstValueFrom(this.api.deleteThread(threadId));
    } catch (error) {
      if (!(error instanceof HttpErrorResponse)) {
        throw error; // A bug, not a failed request. Angular's error handler reports it.
      }
      this._deleteFailure.set(`“${title}” could not be deleted. Please try again.`);
      return false;
    } finally {
      this._deleting.update((ids) => new Set([...ids].filter((id) => id !== threadId)));
    }
    // Taken off here as well, so it is gone even if the refresh fails.
    this.known.update((list) => list?.filter((thread) => thread.thread_id !== threadId));
    this.refresh();
    return true;
  }
}
