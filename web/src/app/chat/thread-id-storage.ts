import { Service } from '@angular/core';

const STORAGE_KEY = 'alphadesk.thread-id';

/**
 * Keeps the current conversation's ID in the browser, so a reload can find it again.
 *
 * Only the ID: the messages live in the API. The browser may refuse storage, for example in
 * a private window. Chat still works then; a reload just starts a new conversation.
 */
@Service()
export class ThreadIdStorage {
  read(): string | undefined {
    try {
      return localStorage.getItem(STORAGE_KEY) ?? undefined;
    } catch {
      return undefined;
    }
  }

  save(threadId: string): void {
    try {
      localStorage.setItem(STORAGE_KEY, threadId);
    } catch {
      // Not kept. See above.
    }
  }

  clear(): void {
    try {
      localStorage.removeItem(STORAGE_KEY);
    } catch {
      // Nothing was kept. See above.
    }
  }
}
