/** Mirrors `src/alphadesk/domain/health.py`. Change both in the same commit. */

export type CheckResult = 'ok' | 'unreachable' | 'not_configured';

/** The report `GET /health` returns. */
export interface HealthReport {
  status: 'ok' | 'degraded';
  postgres: CheckResult;
}
