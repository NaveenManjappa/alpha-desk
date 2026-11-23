import { afterRenderEffect, Component, ElementRef, inject, viewChild } from '@angular/core';

import { ChatSession } from './chat-session';
import { MessageBox } from './message-box/message-box';
import { MessageList } from './message-list/message-list';

/** The chat page. It lays the conversation out; the state is all in `ChatSession`. */
@Component({
  selector: 'app-chat-page',
  imports: [MessageBox, MessageList],
  templateUrl: './chat-page.html',
  styleUrl: './chat-page.css',
})
export class ChatPage {
  protected readonly session = inject(ChatSession);
  private readonly end = viewChild.required<ElementRef<HTMLElement>>('end');

  constructor() {
    // Keep the newest thing in view. Reading the signals is what makes this run again.
    afterRenderEffect(() => {
      this.session.messages();
      this.session.statusLines();
      this.session.failure();
      this.end().nativeElement.scrollIntoView({ block: 'end' });
    });
  }
}
