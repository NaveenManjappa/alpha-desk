import { DatePipe } from '@angular/common';
import { afterNextRender, Component, ElementRef, inject, Injector, viewChild } from '@angular/core';

import { ThreadSummary } from '../../models/thread';
import { ChatSession } from '../chat-session';
import { Conversations } from '../conversations';

/** Earlier conversations: open one, or delete it. */
@Component({
  selector: 'app-conversation-list',
  imports: [DatePipe],
  templateUrl: './conversation-list.html',
  styleUrl: './conversation-list.css',
})
export class ConversationList {
  protected readonly conversations = inject(Conversations);
  protected readonly session = inject(ChatSession);
  private readonly injector = inject(Injector);
  private readonly heading = viewChild.required<ElementRef<HTMLElement>>('heading');

  protected async delete(thread: ThreadSummary): Promise<void> {
    if (!confirm(`Delete “${thread.title}”? This cannot be undone.`)) {
      return;
    }
    if (await this.session.deleteConversation(thread)) {
      afterNextRender({ write: () => this.keepFocus() }, { injector: this.injector });
    }
  }

  /** The focused button is gone with its conversation. Keyboard users go on from the top. */
  private keepFocus(): void {
    if (document.activeElement === document.body) {
      this.heading().nativeElement.focus();
    }
  }
}
