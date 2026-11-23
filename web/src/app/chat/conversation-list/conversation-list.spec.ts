import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { ThreadSummary } from '../../models/thread';
import { APPLE_THREAD as APPLE, NVIDIA_THREAD as NVIDIA } from '../../testing/samples';
import { ChatSession } from '../chat-session';
import { Conversations } from '../conversations';
import { ConversationList } from './conversation-list';

describe('ConversationList', () => {
  const conversations = {
    list: signal<ThreadSummary[] | undefined>(undefined),
    failed: signal(false),
    deleteFailure: signal<string | undefined>(undefined),
    refresh: vi.fn(),
  };
  const session = {
    threadId: signal<string | undefined>(undefined),
    openConversation: vi.fn(),
    canDelete: vi.fn<(id: string) => boolean>(),
    deleteConversation: vi.fn<(thread: ThreadSummary) => Promise<boolean>>(),
  };
  const confirm = vi.fn<(message?: string) => boolean>();
  let fixture: ComponentFixture<ConversationList>;
  let host: HTMLElement;

  beforeEach(async () => {
    vi.resetAllMocks();
    vi.stubGlobal('confirm', confirm);
    session.canDelete.mockReturnValue(true);
    session.deleteConversation.mockResolvedValue(true);
    session.threadId.set(undefined);
    conversations.list.set([NVIDIA, APPLE]);
    conversations.failed.set(false);
    conversations.deleteFailure.set(undefined);
    TestBed.configureTestingModule({
      providers: [
        { provide: Conversations, useValue: conversations },
        { provide: ChatSession, useValue: session },
      ],
    });
    fixture = TestBed.createComponent(ConversationList);
    host = fixture.nativeElement;
    document.body.append(host); // Only an attached element can take the focus.
    await fixture.whenStable();
  });

  afterEach(() => {
    host.remove();
    vi.unstubAllGlobals();
  });

  function button(label: string): HTMLButtonElement {
    const found = [...host.querySelectorAll('button')].find((b) =>
      (b.getAttribute('aria-label') ?? b.textContent).includes(label),
    );
    if (found === undefined) {
      throw new Error(`no button ${label}`);
    }
    return found;
  }

  it('shows each title and last-used time, in the order the API sent', () => {
    const titles = [...host.querySelectorAll('.conversation-title')].map((t) => t.textContent);
    expect(titles).toEqual([NVIDIA.title, APPLE.title]);

    const times = [...host.querySelectorAll('time')];
    expect(times.map((t) => t.getAttribute('datetime'))).toEqual([
      NVIDIA.last_used_at,
      APPLE.last_used_at,
    ]);
    expect(times[0].textContent).toContain('2026');
  });

  it('marks the open conversation', async () => {
    session.threadId.set('apple');
    await fixture.whenStable();

    const marked = host.querySelectorAll('[aria-current=true]');
    expect(marked).toHaveLength(1);
    expect(marked[0].textContent).toContain(APPLE.title);
  });

  it('opens the conversation that is clicked', () => {
    button(APPLE.title).click();

    expect(session.openConversation).toHaveBeenCalledWith('apple');
  });

  it('says when there are no conversations, and when they are still loading', async () => {
    conversations.list.set([]);
    await fixture.whenStable();
    expect(host.textContent).toContain('No conversations yet');

    conversations.list.set(undefined);
    await fixture.whenStable();
    expect(host.textContent).toContain('Loading');
    expect(host.textContent).not.toContain('No conversations yet');
  });

  it('offers to load the list again when that failed', async () => {
    conversations.list.set(undefined);
    conversations.failed.set(true);
    await fixture.whenStable();

    expect(host.querySelector('[role=alert]')?.textContent).toContain('could not be loaded');
    expect(host.textContent).not.toContain('Loading');
    button('Try again').click();
    expect(conversations.refresh).toHaveBeenCalledOnce();
  });

  describe('delete', () => {
    it('asks first, naming the conversation, and then deletes it', () => {
      confirm.mockReturnValue(true);

      button(`Delete ${APPLE.title}`).click();

      expect(confirm.mock.calls[0][0]).toContain(APPLE.title);
      expect(session.deleteConversation).toHaveBeenCalledExactlyOnceWith(APPLE);
    });

    it('deletes nothing when the user cancels', () => {
      confirm.mockReturnValue(false);

      button(`Delete ${APPLE.title}`).click();

      expect(session.deleteConversation).not.toHaveBeenCalled();
    });

    it('is off for a conversation that cannot be deleted now', async () => {
      session.canDelete.mockImplementation((id) => id !== 'apple');
      conversations.list.set([APPLE, NVIDIA]);
      await fixture.whenStable();

      expect(button(`Delete ${APPLE.title}`).disabled).toBe(true);
      expect(button(`Delete ${NVIDIA.title}`).disabled).toBe(false);
    });

    it('keeps the focus in the list when the focused button goes away', async () => {
      confirm.mockReturnValue(true);
      session.deleteConversation.mockImplementation(async () => {
        conversations.list.set([NVIDIA]);
        return true;
      });
      const pressed = button(`Delete ${APPLE.title}`);
      pressed.focus();

      pressed.click();

      await vi.waitFor(() => expect(document.activeElement).toBe(host.querySelector('h2')));
    });

    it('shows why a delete failed, as an alert', async () => {
      conversations.deleteFailure.set('“Apple” could not be deleted.');
      await fixture.whenStable();

      expect(host.querySelector('[role=alert]')?.textContent).toContain('could not be deleted');
    });
  });
});
