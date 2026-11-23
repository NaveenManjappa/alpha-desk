import { ComponentFixture, TestBed } from '@angular/core/testing';

import { MessageBox } from './message-box';

describe('MessageBox', () => {
  let fixture: ComponentFixture<MessageBox>;
  let sent: string[];

  beforeEach(async () => {
    sent = [];
    fixture = TestBed.createComponent(MessageBox);
    fixture.componentRef.setInput('canSend', true);
    fixture.componentInstance.messageSent.subscribe((text) => sent.push(text));
    await fixture.whenStable();
  });

  function box(): HTMLTextAreaElement {
    return fixture.nativeElement.querySelector('textarea');
  }

  function button(): HTMLButtonElement {
    return fixture.nativeElement.querySelector('button');
  }

  async function type(text: string): Promise<void> {
    box().value = text;
    box().dispatchEvent(new Event('input', { bubbles: true }));
    await fixture.whenStable();
  }

  async function press(init: KeyboardEventInit): Promise<KeyboardEvent> {
    const event = new KeyboardEvent('keydown', { key: 'Enter', cancelable: true, ...init });
    box().dispatchEvent(event);
    await fixture.whenStable();
    return event;
  }

  it('sends the trimmed text with the button, and empties the box', async () => {
    await type('  How is Apple doing? ');
    button().click();
    await fixture.whenStable();

    expect(sent).toEqual(['How is Apple doing?']);
    expect(box().value).toBe('');
  });

  it('sends with Enter, without adding a line', async () => {
    await type('Hi');

    expect((await press({})).defaultPrevented).toBe(true);
    expect(sent).toEqual(['Hi']);
  });

  it.each<[string, KeyboardEventInit]>([
    ['Shift+Enter', { shiftKey: true }],
    ['Enter while composing', { isComposing: true }],
  ])('does not send on %s', async (_case, init) => {
    await type('Hi');

    expect((await press(init)).defaultPrevented).toBe(false);
    expect(sent).toEqual([]);
  });

  it('does not send blank text', async () => {
    await type('   ');
    button().click();
    await fixture.whenStable();

    expect(sent).toEqual([]);
  });

  it('keeps what was typed while sending has to wait', async () => {
    fixture.componentRef.setInput('canSend', false);
    await type('Next question');
    await press({});

    expect(button().disabled).toBe(true);
    expect(box().disabled).toBe(false);
    expect(sent).toEqual([]);
    expect(box().value).toBe('Next question');
  });

  it('has a label', () => {
    expect(box().labels?.[0].textContent).toContain('US-listed company');
  });
});
