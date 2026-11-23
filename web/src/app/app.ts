import { Component } from '@angular/core';
import { RouterLink, RouterOutlet } from '@angular/router';

import { HealthIndicator } from './health/health-indicator';

/** The app shell: a header, and a main area where the router puts the current page. */
@Component({
  selector: 'app-root',
  imports: [HealthIndicator, RouterLink, RouterOutlet],
  template: `
    <header>
      <a class="brand" routerLink="/">AlphaDesk</a>
      <app-health-indicator />
    </header>
    <main>
      <router-outlet />
    </main>
  `,
  styleUrl: './app.css',
})
export class App {}
