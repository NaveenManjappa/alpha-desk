import { inject, Service } from '@angular/core';

import { ChatEvent } from '../models/chat-events';
import { ChatRequest } from '../models/chat-request';
import { ApiClient } from './api-client';

/**
 * How long the connection may be silent before it counts as lost. The API sends a ping
 * every 15 seconds while it works, so three missed pings mean nobody is there.
 */
export const IDLE_TIMEOUT_MS = 45_000;

/**
 * Why a stream failed:
 *
 * - `unreachable`: the run never started. No connection, or the server failed.
 * - `rejected`: the API refused the message, so sending it again will not help.
 * - `lost`: the run started, but its end never arrived.
 */
export type ChatStreamFailure = 'unreachable' | 'rejected' | 'lost';

/** The stream failed. Different from an `error` event, which is the API reporting a failure. */
export class ChatStreamError extends Error {
  override readonly name = 'ChatStreamError';

  constructor(
    readonly reason: ChatStreamFailure,
    cause?: unknown,
  ) {
    super(`Chat stream failed: ${reason}`, { cause });
  }
}

/**
 * Sends a message and turns the streamed response into typed events. All streaming goes
 * through here.
 *
 * `fetch` rather than `EventSource`, which can only send a GET. And not Angular's
 * `resource()`, which its docs reserve for reads: it cancels a request whenever its inputs
 * change, and this POST runs an agent and adds to a conversation.
 */
@Service()
export class ChatStream {
  private readonly api = inject(ApiClient);

  /**
   * Run one chat turn. Read it with `for await`.
   *
   * @param request The message and its conversation.
   * @param signal Aborting it closes the connection and ends the stream without an error.
   * @yields Events as they arrive. The last one is always `final` or `error`.
   * @throws {ChatStreamError} The stream ended in any other way.
   */
  async *send(request: ChatRequest, signal?: AbortSignal): AsyncGenerator<ChatEvent> {
    // One switch that closes the connection, whether the caller or the idle timer throws it.
    const connection = new AbortController();
    const close = () => connection.abort();
    signal?.addEventListener('abort', close, { once: true });
    let idleTimer = setTimeout(close, IDLE_TIMEOUT_MS);
    const onActivity = () => {
      clearTimeout(idleTimer);
      idleTimer = setTimeout(close, IDLE_TIMEOUT_MS);
    };

    try {
      const body = await this.connect(request, connection.signal);
      for await (const data of readServerSentEvents(body, connection.signal, onActivity)) {
        const event = parseEvent(data);
        if (event === undefined) {
          continue;
        }
        yield event;
        if (event.type === 'final' || event.type === 'error') {
          return;
        }
      }
      throw new ChatStreamError('lost');
    } catch (error) {
      if (signal?.aborted) {
        return;
      }
      throw error instanceof ChatStreamError ? error : new ChatStreamError('lost', error);
    } finally {
      clearTimeout(idleTimer);
      signal?.removeEventListener('abort', close);
      close();
    }
  }

  /** Post the request and return the response body, not yet read. */
  private async connect(
    request: ChatRequest,
    signal: AbortSignal,
  ): Promise<ReadableStream<Uint8Array>> {
    let response: Response;
    try {
      response = await fetch(this.api.chatUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
        signal,
      });
    } catch (error) {
      throw new ChatStreamError('unreachable', error);
    }
    if (response.status === 422) {
      throw new ChatStreamError('rejected');
    }
    if (!response.ok || response.body === null) {
      throw new ChatStreamError('unreachable');
    }
    return response.body;
  }
}

/**
 * Read the `data` of each Server-Sent Event in `body`.
 *
 * Network pieces do not line up with events: one piece may hold several events, or half of
 * one, or half of a character. So text is buffered until the blank line that ends an event.
 * What is left over when the body ends is an event that was cut off, and is dropped.
 */
async function* readServerSentEvents(
  body: ReadableStream<Uint8Array>,
  signal: AbortSignal,
  onActivity: () => void,
): AsyncGenerator<string> {
  const reader = body.getReader();
  // Cancelling ends a read that is waiting. It fails if the body already has, which is fine.
  const cancel = () => void reader.cancel().catch(() => undefined);
  signal.addEventListener('abort', cancel, { once: true });
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        return;
      }
      onActivity();
      buffer += decoder.decode(value, { stream: true });
      const blocks = buffer.split(/\r?\n\r?\n/);
      buffer = blocks.pop() ?? '';
      for (const block of blocks) {
        const data = dataOf(block);
        if (data !== '') {
          yield data;
        }
      }
    }
  } finally {
    signal.removeEventListener('abort', cancel);
    cancel();
  }
}

/** An event's `data` lines, joined. Empty for a block without any, such as a ping. */
function dataOf(block: string): string {
  return block
    .split(/\r?\n/)
    .filter((line) => line.startsWith('data:'))
    .map((line) => line.slice('data:'.length).trimStart())
    .join('\n');
}

const EVENT_TYPES: Record<ChatEvent['type'], true> = {
  status: true,
  token: true,
  final: true,
  error: true,
};

/** The event in `data`, or undefined for a type this version of the app does not know. */
function parseEvent(data: string): ChatEvent | undefined {
  const event: unknown = JSON.parse(data);
  return isChatEvent(event) ? event : undefined;
}

/**
 * Only the type is checked. The API built the rest from the same contract, and a full check
 * would be a second copy of it to keep in step.
 */
function isChatEvent(event: unknown): event is ChatEvent {
  return (
    typeof event === 'object' &&
    event !== null &&
    'type' in event &&
    typeof event.type === 'string' &&
    Object.hasOwn(EVENT_TYPES, event.type)
  );
}
