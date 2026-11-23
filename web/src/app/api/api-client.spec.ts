import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';
import { firstValueFrom } from 'rxjs';

import { HealthReport } from '../models/health';
import { ApiClient } from './api-client';

describe('ApiClient.getHealth', () => {
  let client: ApiClient;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClientTesting()] });
    client = TestBed.inject(ApiClient);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('returns the report', async () => {
    const report: HealthReport = { status: 'ok', postgres: 'ok' };
    const result = firstValueFrom(client.getHealth());

    http.expectOne({ method: 'GET', url: '/health' }).flush(report);

    await expect(result).resolves.toEqual(report);
  });

  it('returns the report a degraded API sends with its 503', async () => {
    const report: HealthReport = { status: 'degraded', postgres: 'unreachable' };
    const result = firstValueFrom(client.getHealth());

    http.expectOne('/health').flush(report, { status: 503, statusText: 'Service Unavailable' });

    await expect(result).resolves.toEqual(report);
  });

  it.each([
    ['a 503 from something other than the API', 503, 'no server available'],
    ['a 503 with an empty body', 503, null],
    ['a server error', 500, { detail: 'boom' }],
  ])('fails on %s', async (_case, status, body) => {
    const result = firstValueFrom(client.getHealth());

    http.expectOne('/health').flush(body, { status, statusText: 'Failed' });

    await expect(result).rejects.toMatchObject({ status });
  });

  it('fails when there is no connection', async () => {
    const result = firstValueFrom(client.getHealth());

    http.expectOne('/health').error(new ProgressEvent('error'));

    await expect(result).rejects.toMatchObject({ status: 0 });
  });
});
