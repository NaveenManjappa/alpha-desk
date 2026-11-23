import { Component, input, output, signal } from '@angular/core';
import { form, FormField, FormRoot } from '@angular/forms/signals';

/**
 * Where the user types. Enter sends, Shift+Enter starts a new line. The box stays usable
 * while a run is in progress, so the next question can be typed; only sending waits.
 */
@Component({
  selector: 'app-message-box',
  imports: [FormField, FormRoot],
  template: `
    <form [formRoot]="messageForm">
      <label for="message">Ask about a US-listed company</label>
      <textarea
        id="message"
        rows="2"
        [formField]="messageForm.text"
        (keydown.enter)="sendOnEnter($event)"
      ></textarea>
      <button type="submit" class="primary" [disabled]="!canSend()">Send</button>
    </form>
  `,
  styles: `
    form {
      display: grid;
      grid-template-columns: 1fr auto;
      gap: 0.5rem;
      align-items: end;
    }

    label {
      grid-column: 1 / -1;
      font-size: 0.875rem;
    }

    textarea {
      min-width: 0;
      padding: 0.5rem;
      border: 1px solid var(--color-muted);
      border-radius: 0.5rem;
      font: inherit;
      resize: vertical;
    }
  `,
})
export class MessageBox {
  readonly canSend = input.required<boolean>();
  readonly messageSent = output<string>();

  private readonly draft = signal({ text: '' });
  protected readonly messageForm = form(this.draft, {
    submission: { action: async () => this.send() },
  });

  protected sendOnEnter(event: Event): void {
    // While composing, as when typing Japanese, Enter accepts a suggestion instead.
    if (event instanceof KeyboardEvent && event.isComposing) {
      return;
    }
    event.preventDefault();
    this.send();
  }

  private send(): void {
    const text = this.draft().text.trim();
    if (text === '' || !this.canSend()) {
      return;
    }
    this.messageSent.emit(text);
    this.messageForm().reset({ text: '' });
  }
}
