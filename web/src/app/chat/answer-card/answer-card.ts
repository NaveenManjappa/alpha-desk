import { DatePipe, DecimalPipe } from '@angular/common';
import { Component, input } from '@angular/core';

import { Answer } from '../../models/answer';

/** One answer, with a source link for every figure. Shows `verified` as the API sent it. */
@Component({
  selector: 'app-answer-card',
  imports: [DatePipe, DecimalPipe],
  templateUrl: './answer-card.html',
  styleUrl: './answer-card.css',
  host: { '[attr.data-verified]': 'answer().verified' },
})
export class AnswerCard {
  readonly answer = input.required<Answer>();
}
