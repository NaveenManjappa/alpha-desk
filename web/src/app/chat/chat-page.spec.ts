import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ThreadMessage, ThreadSummary } from '../models/thread';
import { ANSWER_MESSAGE } from '../testing/samples';
import { ChatPage } from './chat-page';
import { ChatSession } from './chat-session';
import { Conversations } from './conversations';

describe('ChatPage', () => {
  const session = {
    messages: signal<ThreadMessage[]>([]),
    statusLines: signal<string[]>([]),
    failure: signal<string | undefined>(undefined),
    running: signal(false),
    loadingHistory: signal(false),
    historyFailed: signal(false),
    canSend: signal(true),
    threadId: signal<string | undefined>(undefined),
    send: vi.fn(),
    startNewConversation: vi.fn(),
    reloadHistory: vi.fn(),
  };
  const conversations = {
    list: signal<ThreadSummary[] | undefined>([]),
    failed: signal(false),
    deleteFailure: signal<string | undefined>(undefined),
  };
  let fixture: ComponentFixture<ChatPage>;
  let host: HTMLElement;

  beforeEach(async () => {
    Element.prototype.scrollIntoView = vi.fn(); // jsdom lays nothing out, so it has none.
    session.messages.set([]);
    session.statusLines.set([]);
    session.failure.set(undefined);
    session.running.set(false);
    session.loadingHistory.set(false);
    session.historyFailed.set(false);
    conversations.failed.set(false);
    vi.clearAllMocks();
    TestBed.configureTestingModule({
      providers: [
        { provide: ChatSession, useValue: session },
        { provide: Conversations, useValue: conversations },
      ],
    });
    fixture = TestBed.createComponent(ChatPage);
    host = fixture.nativeElement;
    await fixture.whenStable();
  });

  function button(label: string): HTMLButtonElement | undefined {
    return [...host.querySelectorAll('button')].find((b) => b.textContent.trim() === label);
  }

  it('shows the conversation', async () => {
    session.messages.set([{ type: 'question', text: 'Apple?' }, ANSWER_MESSAGE]);
    await fixture.whenStable();

    expect(host.querySelector('[role=log]')?.textContent).toContain('Apple?');
    expect(host.querySelectorAll('app-answer-card')).toHaveLength(1);
  });

  it('shows status lines only while a run is in progress', async () => {
    session.running.set(true);
    session.statusLines.set(['Getting the price', 'Reading financials']);
    await fixture.whenStable();
    const steps = [...host.querySelectorAll('[role=status] .step')].map((s) => s.textContent);
    expect(steps).toEqual(['Getting the price', 'Reading financials']);

    session.running.set(false);
    await fixture.whenStable();
    expect(host.querySelector('[role=status]')?.textContent.trim()).toBe('');
  });

  it('shows a failure as an alert', async () => {
    session.failure.set('The connection was lost.');
    await fixture.whenStable();

    expect(host.querySelector('.chat [role=alert]')?.textContent).toContain(
      'The connection was lost.',
    );
  });

  it('still takes a message when the list of conversations fails to load', async () => {
    conversations.failed.set(true);
    await fixture.whenStable();

    expect(host.querySelector('app-conversation-list')?.textContent).toContain(
      'could not be loaded',
    );
    expect(button('Send')?.disabled).toBe(false);
  });

  it('offers to load the conversation again when that failed', async () => {
    session.historyFailed.set(true);
    await fixture.whenStable();
    button('Try again')?.click();

    expect(session.reloadHistory).toHaveBeenCalledOnce();
  });

  it('sends what the message box gives it', async () => {
    const box = host.querySelector('textarea');
    if (box === null) {
      throw new Error('no message box');
    }
    box.value = 'How is Apple doing?';
    box.dispatchEvent(new Event('input', { bubbles: true }));
    button('Send')?.click();
    await fixture.whenStable();

    expect(session.send).toHaveBeenCalledWith('How is Apple doing?');
  });

  it('starts a new conversation', () => {
    button('New conversation')?.click();

    expect(session.startNewConversation).toHaveBeenCalledOnce();
  });

  it('brings the newest message into view', async () => {
    vi.mocked(Element.prototype.scrollIntoView).mockClear();
    session.messages.set([{ type: 'question', text: 'Apple?' }]);
    await fixture.whenStable();

    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
  });
});
