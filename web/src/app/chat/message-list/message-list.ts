import { Component, input } from '@angular/core';

import { ThreadMessage } from '../../models/thread';
import { AnswerCard } from '../answer-card/answer-card';
import { UsageLine } from '../usage-line/usage-line';

/**
 * The conversation. The message's type picks how it is shown, so a new result type is a new
 * component and one more case here. `@default never` makes the build fail until it has one.
 */
@Component({
  selector: 'app-message-list',
  imports: [AnswerCard, UsageLine],
  template: `
    <ol>
      @for (message of messages(); track $index) {
        <li>
          @switch (message.type) {
            @case ('question') {
              <p class="question"><span class="visually-hidden">You: </span>{{ message.text }}</p>
            }
            @case ('answer') {
              <app-answer-card [answer]="message.answer" />
              <app-usage-line [usage]="message.usage" />
            }
            @default never(message);
          }
        </li>
      }
    </ol>
  `,
  styles: `
    ol {
      display: grid;
      gap: 1rem;
      margin: 0;
      padding: 0;
      list-style: none;
    }

    li {
      min-width: 0;
    }

    .question {
      width: fit-content;
      max-width: 85%;
      margin: 0 0 0 auto;
      padding: 0.5rem 0.75rem;
      border-radius: 0.5rem;
      background: var(--color-surface);
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }
  `,
})
export class MessageList {
  readonly messages = input.required<readonly ThreadMessage[]>();
}
