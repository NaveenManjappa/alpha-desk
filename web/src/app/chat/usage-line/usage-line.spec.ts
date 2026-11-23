import { TestBed } from '@angular/core/testing';

import { USAGE } from '../../testing/samples';
import { UsageLine } from './usage-line';

describe('UsageLine', () => {
  it('formats the time, tokens and estimated cost', async () => {
    const fixture = TestBed.createComponent(UsageLine);
    fixture.componentRef.setInput('usage', USAGE);
    await fixture.whenStable();

    const text = (fixture.nativeElement as HTMLElement).textContent;
    expect(text.replace(/\s+/g, ' ').trim()).toBe('4.2 s · 3,180 tokens · $0.0041 est.');
  });
});
