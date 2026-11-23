import { TestBed } from '@angular/core/testing';

import { Answer } from '../../models/answer';
import { ANSWER } from '../../testing/samples';
import { AnswerCard } from './answer-card';

async function render(answer: Answer): Promise<HTMLElement> {
  const fixture = TestBed.createComponent(AnswerCard);
  fixture.componentRef.setInput('answer', answer);
  await fixture.whenStable();
  return fixture.nativeElement;
}

function hrefs(host: HTMLElement, selector: string): (string | null)[] {
  return [...host.querySelectorAll(selector)].map((link) => link.getAttribute('href'));
}

describe('AnswerCard', () => {
  it('shows the summary, the date and the disclaimer', async () => {
    const host = await render(ANSWER);

    expect(host.querySelector('.summary')?.textContent).toBe(ANSWER.summary);
    expect(host.querySelector('time')?.getAttribute('datetime')).toBe(ANSWER.as_of);
    expect(host.querySelector('time')?.textContent).toContain('2026');
    expect(host.textContent).toContain(ANSWER.disclaimer);
  });

  it('gives every figure its value, unit, period and own source link', async () => {
    const host = await render(ANSWER);

    const rows = [...host.querySelectorAll('tbody tr')].map((row) =>
      [...row.querySelectorAll('th, td')].map((cell) => cell.textContent.trim()),
    );
    expect(rows).toEqual([
      ['Revenue', '416,161,000,000', 'USD', 'FY2025', 'Source'],
      ['Diluted EPS', '7.46', 'USD per share', 'FY2025', 'Source'],
    ]);
    expect(hrefs(host, 'tbody a')).toEqual(ANSWER.key_figures.map((f) => f.source_url));
    expect(host.querySelector('tbody a')?.getAttribute('aria-label')).toBe(
      'Source for Revenue, FY2025',
    );
  });

  it('lists every source', async () => {
    expect(hrefs(await render(ANSWER), 'section a')).toEqual(ANSWER.sources);
  });

  it('opens links in a new tab that cannot reach back to this one', async () => {
    const host = await render(ANSWER);

    for (const link of host.querySelectorAll('a')) {
      expect(link.target).toBe('_blank');
      expect(link.rel).toContain('noopener');
    }
  });

  it('never makes a link that runs a script', async () => {
    // A source is text the model wrote. Angular makes an unsafe address harmless.
    const host = await render({ ...ANSWER, sources: ['javascript:alert(1)'] });

    expect(hrefs(host, 'section a')).toEqual(['unsafe:javascript:alert(1)']);
  });

  it('leaves out the table and the sources when there are none', async () => {
    const host = await render({ ...ANSWER, key_figures: [], sources: [] });

    expect(host.querySelector('table')).toBeNull();
    expect(host.querySelector('section')).toBeNull();
  });

  it('looks different when it is not verified, in words as well as colour', async () => {
    const verified = await render(ANSWER);
    const unverified = await render({ ...ANSWER, verified: false });

    expect(verified.querySelector('.badge')?.textContent).toBe('Verified');
    expect(verified.querySelector('.warning')).toBeNull();
    expect(unverified.querySelector('.badge')?.textContent).toBe('Not verified');
    expect(unverified.querySelector('.warning')).not.toBeNull();
    expect(unverified.getAttribute('data-verified')).toBe('false');
  });
});
