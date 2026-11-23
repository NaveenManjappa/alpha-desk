import { TestBed } from '@angular/core/testing';

import { ChatEvent } from '../models/chat-events';
import { ChatRequest } from '../models/chat-request';
import { ChatStream, ChatStreamError, IDLE_TIMEOUT_MS } from './chat-stream';

const REQUEST: ChatRequest = { message: 'How is Apple doing?', thread_id: 't1' };

const STATUS: ChatEvent = {
  type: 'status',
  tool: 'get_quote',
  message: 'Getting the latest share price',
};
const TOKEN: ChatEvent = { type: 'token', text: 'Looking…' };
const FINAL: ChatEvent = {
  type: 'final',
  answer: {
    summary: 'Apple’s revenue grew.',
    key_figures: [],
    sources: [],
    as_of: '2026-11-23T10:00:00Z',
    verified: true,
    disclaimer: 'Research, not advice.',
  },
  usage: {
    duration_seconds: 4.2,
    input_tokens: 3000,
    output_tokens: 180,
    total_tokens: 3180,
    estimated_cost_usd: 0.0041,
  },
};
const ERROR: ChatEvent = { type: 'error', message: 'Something went wrong.' };

/** One event exactly as the API writes it. */
function sse(event: object & { type: string }): string {
  return `event: ${event.type}\ndata: ${JSON.stringify(event)}\n\n`;
}

/** A fake response body the test feeds by hand, piece by piece. */
class FakeBody {
  private controller!: ReadableStreamDefaultController<Uint8Array>;
  cancelled = false;

  readonly stream = new ReadableStream<Uint8Array>({
    start: (controller) => {
      this.controller = controller;
    },
    cancel: () => {
      this.cancelled = true;
    },
  });

  send(text: string | Uint8Array): this {
    this.controller.enqueue(typeof text === 'string' ? new TextEncoder().encode(text) : text);
    return this;
  }

  end(): void {
    this.controller.close();
  }

  /** The connection drops: the browser makes the read fail. */
  drop(): void {
    this.controller.error(new TypeError('network error'));
  }
}

describe('ChatStream', () => {
  let body: FakeBody;
  let fetchSpy: ReturnType<typeof vi.fn<typeof fetch>>;

  beforeEach(() => {
    body = new FakeBody();
    fetchSpy = vi.fn<typeof fetch>(async () => new Response(body.stream));
    vi.stubGlobal('fetch', fetchSpy);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  function open(signal?: AbortSignal): AsyncGenerator<ChatEvent> {
    return TestBed.inject(ChatStream).send(REQUEST, signal);
  }

  /** Read to the end, returning the events seen and the error that ended it, if any. */
  async function collect(stream = open()): Promise<{ events: ChatEvent[]; error: unknown }> {
    const events: ChatEvent[] = [];
    try {
      for await (const event of stream) {
        events.push(event);
      }
    } catch (error) {
      return { events, error };
    }
    return { events, error: undefined };
  }

  it('posts the request as JSON to the API', async () => {
    body.send(sse(FINAL)).end();

    await collect();

    const [url, init] = fetchSpy.mock.calls[0];
    expect(url).toBe('/chat');
    expect(init?.method).toBe('POST');
    expect(new Headers(init?.headers).get('Content-Type')).toBe('application/json');
    expect(JSON.parse(String(init?.body))).toEqual(REQUEST);
  });

  describe('a normal run', () => {
    it('yields each event, typed and in order, and then ends', async () => {
      body.send(sse(STATUS)).send(sse(TOKEN)).send(sse(FINAL)).end();

      expect(await collect()).toEqual({ events: [STATUS, TOKEN, FINAL], error: undefined });
    });

    it('yields an event as soon as it arrives, not when the stream ends', async () => {
      const stream = open();
      body.send(sse(STATUS));

      expect((await stream.next()).value).toEqual(STATUS);

      body.send(sse(FINAL));
      expect((await stream.next()).value).toEqual(FINAL);
    });

    it('splits several events that arrive in one piece', async () => {
      body.send(sse(STATUS) + sse(TOKEN) + sse(FINAL)).end();

      expect((await collect()).events).toEqual([STATUS, TOKEN, FINAL]);
    });

    it('joins events cut anywhere, even in the middle of a character', async () => {
      // One byte at a time is every possible cut. The answer holds a multi-byte character.
      for (const byte of new TextEncoder().encode(sse(STATUS) + sse(FINAL))) {
        body.send(new Uint8Array([byte]));
      }
      body.end();

      expect((await collect()).events).toEqual([STATUS, FINAL]);
    });

    it('reads streams whose lines end in CRLF', async () => {
      body.send((sse(STATUS) + sse(FINAL)).replaceAll('\n', '\r\n')).end();

      expect((await collect()).events).toEqual([STATUS, FINAL]);
    });

    it('ignores keep-alive pings and event types it does not know', async () => {
      body
        .send(': ping\n\n')
        .send(sse({ type: 'from-a-newer-api' }))
        .send(sse(FINAL))
        .end();

      expect((await collect()).events).toEqual([FINAL]);
    });

    it('stops at the final event and closes the connection', async () => {
      body.send(sse(FINAL) + sse(STATUS));

      expect((await collect()).events).toEqual([FINAL]);
      expect(body.cancelled).toBe(true);
    });
  });

  it('yields an error event and then ends normally', async () => {
    body.send(sse(STATUS)).send(sse(ERROR)).end();

    expect(await collect()).toEqual({ events: [STATUS, ERROR], error: undefined });
  });

  describe('a stream cut short', () => {
    it('fails as lost when it ends without a final or error event', async () => {
      body.send(sse(STATUS)).end();

      const { events, error } = await collect();

      expect(events).toEqual([STATUS]);
      expect(error).toBeInstanceOf(ChatStreamError);
      expect(error).toMatchObject({ reason: 'lost' });
    });

    it('fails as lost when it ends in the middle of the final event', async () => {
      body.send(sse(STATUS)).send(sse(FINAL).slice(0, -20)).end();

      const { events, error } = await collect();

      expect(events).toEqual([STATUS]);
      expect(error).toMatchObject({ reason: 'lost' });
    });

    it('fails as lost when the connection drops', async () => {
      const stream = open();
      body.send(sse(STATUS));
      await stream.next();
      body.drop();

      expect(await collect(stream)).toMatchObject({ events: [], error: { reason: 'lost' } });
    });

    it('fails as lost when an event is not readable', async () => {
      body.send('event: final\ndata: {not json\n\n').end();

      expect((await collect()).error).toMatchObject({ reason: 'lost' });
    });

    it('fails as lost when nothing arrives for too long, not even a ping', async () => {
      vi.useFakeTimers();
      const result = collect();
      body.send(sse(STATUS));
      await vi.advanceTimersByTimeAsync(IDLE_TIMEOUT_MS);

      expect(await result).toMatchObject({ events: [STATUS], error: { reason: 'lost' } });
    });

    it('waits as long as pings keep arriving', async () => {
      vi.useFakeTimers();
      const result = collect();
      for (let ping = 0; ping < 5; ping++) {
        await vi.advanceTimersByTimeAsync(IDLE_TIMEOUT_MS - 1);
        body.send(': ping\n\n');
        await vi.advanceTimersByTimeAsync(0);
      }
      body.send(sse(FINAL));
      await vi.advanceTimersByTimeAsync(0);

      expect(await result).toEqual({ events: [FINAL], error: undefined });
    });
  });

  describe('a run that never starts', () => {
    it('fails as unreachable when there is no connection', async () => {
      fetchSpy.mockRejectedValue(new TypeError('Failed to fetch'));

      expect((await collect()).error).toMatchObject({ reason: 'unreachable' });
    });

    it('fails as unreachable when the server answers with an error', async () => {
      // What the dev-server proxy sends when the API is not running.
      fetchSpy.mockResolvedValue(new Response('', { status: 500 }));

      expect((await collect()).error).toMatchObject({ reason: 'unreachable' });
    });

    it('fails as rejected when the API refuses the message', async () => {
      fetchSpy.mockResolvedValue(new Response('{"detail": []}', { status: 422 }));

      expect((await collect()).error).toMatchObject({ reason: 'rejected' });
    });
  });

  it('ends quietly when the caller aborts, and closes the connection', async () => {
    const controller = new AbortController();
    const stream = open(controller.signal);
    body.send(sse(STATUS));
    await stream.next();

    controller.abort();

    expect(await collect(stream)).toEqual({ events: [], error: undefined });
    expect(body.cancelled).toBe(true);
  });
});
