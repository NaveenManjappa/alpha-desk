import { CurrencyPipe, DecimalPipe } from '@angular/common';
import { Component, input } from '@angular/core';

import { RunUsage } from '../../models/usage';

/** What a run took, on one line. The API worked the values out; this only formats them. */
@Component({
  selector: 'app-usage-line',
  imports: [CurrencyPipe, DecimalPipe],
  template: `
    {{ usage().duration_seconds | number: '1.1-1' }} s · {{ usage().total_tokens | number }} tokens
    · {{ usage().estimated_cost_usd | currency: 'USD' : 'symbol' : '1.4-4' }} est.
  `,
  styles: `
    :host {
      display: block;
      color: var(--color-muted);
      font-size: 0.8125rem;
    }
  `,
})
export class UsageLine {
  readonly usage = input.required<RunUsage>();
}
