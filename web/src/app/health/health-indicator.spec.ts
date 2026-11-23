import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';

import { HealthIndicator } from './health-indicator';
import { ApiHealth, HealthMonitor } from './health-monitor';

describe('HealthIndicator', () => {
  it.each<[ApiHealth, string]>([
    ['checking', 'Checking API'],
    ['ok', 'API connected'],
    ['degraded', 'API degraded'],
    ['unreachable', 'API unreachable'],
  ])('says in words that the API is %s', async (health, label) => {
    TestBed.configureTestingModule({
      providers: [{ provide: HealthMonitor, useValue: { health: signal(health) } }],
    });
    const fixture = TestBed.createComponent(HealthIndicator);
    await fixture.whenStable();

    const host: HTMLElement = fixture.nativeElement;
    expect(host.textContent?.trim()).toBe(label);
    expect(host.getAttribute('role')).toBe('status');
    expect(host.getAttribute('data-health')).toBe(health);
  });
});
