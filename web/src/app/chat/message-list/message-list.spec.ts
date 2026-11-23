import { TestBed } from '@angular/core/testing';

import { ANSWER_MESSAGE } from '../../testing/samples';
import { MessageList } from './message-list';

describe('MessageList', () => {
  it('shows each message by its type, in order, with usage under each answer', async () => {
    const fixture = TestBed.createComponent(MessageList);
    fixture.componentRef.setInput('messages', [
      { type: 'question', text: 'How is <b>Apple</b> doing?' },
      ANSWER_MESSAGE,
      { type: 'question', text: 'And its revenue?' },
    ]);
    await fixture.whenStable();

    const items = [...(fixture.nativeElement as HTMLElement).querySelectorAll('ol > li')];
    expect(items).toHaveLength(3);
    // As text, not as HTML.
    expect(items[0].textContent).toContain('How is <b>Apple</b> doing?');
    expect(items[0].querySelector('app-answer-card')).toBeNull();
    expect(items[1].querySelector('app-answer-card')).not.toBeNull();
    expect(items[1].querySelector('app-usage-line')?.textContent).toContain('3,180 tokens');
    expect(items[2].textContent).toContain('And its revenue?');
  });
});
