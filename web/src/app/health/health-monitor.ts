import { inject, Service } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { catchError, exhaustMap, map, of, timer } from 'rxjs';

import { ApiClient } from '../api/api-client';
import { HealthReport } from '../models/health';

/**
 * What the API says about itself, plus the two cases where it has said nothing: no reply
 * yet, and no reply at all.
 */
export type ApiHealth = HealthReport['status'] | 'checking' | 'unreachable';

const POLL_INTERVAL_MS = 10_000;

/** Asks the API for its health at a steady interval and holds the latest result. */
@Service()
export class HealthMonitor {
  private readonly api = inject(ApiClient);

  readonly health = toSignal(
    timer(0, POLL_INTERVAL_MS).pipe(
      // exhaustMap skips a tick while a check is still running, so checks never pile up.
      exhaustMap(() =>
        this.api.getHealth().pipe(
          map((report): ApiHealth => report.status),
          // Caught inside the inner stream, so one failed check does not end the polling.
          catchError(() => of<ApiHealth>('unreachable')),
        ),
      ),
    ),
    { initialValue: 'checking' },
  );
}
