import { TestBed } from '@angular/core/testing';
import { NEVER, Observable, of, throwError } from 'rxjs';

import { ApiClient } from '../api/api-client';
import { HealthReport } from '../models/health';
import { HealthMonitor } from './health-monitor';

const POLL_MS = 10_000;
const OK = of<HealthReport>({ status: 'ok', postgres: 'ok' });
const DEGRADED = of<HealthReport>({ status: 'degraded', postgres: 'unreachable' });
const DOWN = throwError(() => new Error('no connection'));

describe('HealthMonitor', () => {
  const getHealth = vi.fn<() => Observable<HealthReport>>();

  beforeEach(() => {
    vi.useFakeTimers();
    getHealth.mockReset();
    TestBed.configureTestingModule({
      providers: [{ provide: ApiClient, useValue: { getHealth } }],
    });
  });

  afterEach(() => vi.useRealTimers());

  it('is checking until the first reply, then shows the status the API sent', () => {
    getHealth.mockReturnValue(OK);
    const monitor = TestBed.inject(HealthMonitor);
    expect(monitor.health()).toBe('checking');

    vi.advanceTimersByTime(0);

    expect(monitor.health()).toBe('ok');
  });

  it('passes on a degraded status', () => {
    getHealth.mockReturnValue(DEGRADED);
    const monitor = TestBed.inject(HealthMonitor);

    vi.advanceTimersByTime(0);

    expect(monitor.health()).toBe('degraded');
  });

  it('turns unreachable when the API stops, and recovers when it is back', () => {
    getHealth.mockReturnValueOnce(OK).mockReturnValueOnce(DOWN).mockReturnValueOnce(OK);
    const monitor = TestBed.inject(HealthMonitor);
    vi.advanceTimersByTime(0);
    expect(monitor.health()).toBe('ok');

    vi.advanceTimersByTime(POLL_MS);
    expect(monitor.health()).toBe('unreachable');

    vi.advanceTimersByTime(POLL_MS);
    expect(monitor.health()).toBe('ok');
  });

  it('does not start a check while one is still running', () => {
    getHealth.mockReturnValue(NEVER);
    TestBed.inject(HealthMonitor);

    vi.advanceTimersByTime(3 * POLL_MS);

    expect(getHealth).toHaveBeenCalledTimes(1);
  });
});
