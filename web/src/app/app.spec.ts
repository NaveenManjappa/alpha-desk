import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideRouter, Router } from '@angular/router';

import { App } from './app';
import { routes } from './app.routes';
import { HealthMonitor } from './health/health-monitor';

describe('App', () => {
  beforeEach(() => {
    localStorage.clear(); // No conversation to fetch.
    Element.prototype.scrollIntoView = vi.fn(); // jsdom lays nothing out, so it has none.
  });

  it('shows the header, the health indicator and the chat page', async () => {
    TestBed.configureTestingModule({
      providers: [
        provideRouter(routes),
        { provide: HealthMonitor, useValue: { health: signal('ok') } },
      ],
    });
    const fixture = TestBed.createComponent(App);
    await TestBed.inject(Router).navigateByUrl('/');
    await fixture.whenStable();

    const host: HTMLElement = fixture.nativeElement;
    expect(host.querySelector('header')?.textContent).toContain('AlphaDesk');
    expect(host.querySelector('header')?.textContent).toContain('API connected');
    expect(host.querySelector('main h1')?.textContent).toBe('Chat');
    expect(document.title).toBe('Chat | AlphaDesk');
  });
});
