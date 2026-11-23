import { Component, computed, inject } from '@angular/core';

import { ApiHealth, HealthMonitor } from './health-monitor';

const LABELS: Record<ApiHealth, string> = {
  checking: 'Checking API',
  ok: 'API connected',
  degraded: 'API degraded',
  unreachable: 'API unreachable',
};

/**
 * A coloured dot and a label. The label carries the meaning, so nothing depends on seeing
 * the colour, and role="status" makes screen readers announce a change.
 */
@Component({
  selector: 'app-health-indicator',
  template: `
    <span class="dot" aria-hidden="true"></span>
    <span>{{ label() }}</span>
  `,
  styleUrl: './health-indicator.css',
  host: { role: 'status', '[attr.data-health]': 'health()' },
})
export class HealthIndicator {
  protected readonly health = inject(HealthMonitor).health;
  protected readonly label = computed(() => LABELS[this.health()]);
}
