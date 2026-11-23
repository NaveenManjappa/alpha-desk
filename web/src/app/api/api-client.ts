import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { inject, Service } from '@angular/core';
import { catchError, Observable, of, throwError } from 'rxjs';

import { HealthReport } from '../models/health';
import { Thread } from '../models/thread';

/**
 * Where the API is. Empty means "the same address this page came from": the dev server
 * proxies API paths (src/proxy.conf.mjs), and in production the API serves this app.
 */
const API_BASE_URL = '';

/** Longer than the API's own Postgres check (5 seconds), so a slow report still arrives. */
const HEALTH_TIMEOUT_MS = 8_000;

const THREAD_TIMEOUT_MS = 10_000;

/** The only place that knows the API's address and paths. Components never call HTTP. */
@Service()
export class ApiClient {
  private readonly http = inject(HttpClient);

  /** Where `ChatStream` sends messages. Streaming is its job; knowing the address is ours. */
  readonly chatUrl = `${API_BASE_URL}/chat`;

  /**
   * Fetch the API's health report.
   *
   * A degraded API answers 503 with a report in the body. HttpClient treats every 503 as
   * an error, so that one is turned back into the report it is. Anything else, such as no
   * connection, stays an error.
   */
  getHealth(): Observable<HealthReport> {
    return this.http
      .get<HealthReport>(`${API_BASE_URL}/health`, { timeout: HEALTH_TIMEOUT_MS })
      .pipe(
        catchError((error: unknown) => {
          if (
            error instanceof HttpErrorResponse &&
            error.status === 503 &&
            isHealthReport(error.error)
          ) {
            return of(error.error);
          }
          return throwError(() => error);
        }),
      );
  }

  /** Fetch a conversation's messages. A thread nobody has used comes back empty. */
  getThread(threadId: string): Observable<Thread> {
    return this.http.get<Thread>(`${API_BASE_URL}/threads/${encodeURIComponent(threadId)}`, {
      timeout: THREAD_TIMEOUT_MS,
    });
  }
}

/** A proxy in front of the API can also answer 503, with a body that is not a report. */
function isHealthReport(body: unknown): body is HealthReport {
  return typeof body === 'object' && body !== null && 'status' in body && 'postgres' in body;
}
