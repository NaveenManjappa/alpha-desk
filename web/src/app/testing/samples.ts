/** Sample data for the tests, shaped exactly as the API sends it. Never part of the app. */

import { Answer } from '../models/answer';
import { AnswerMessage } from '../models/thread';
import { RunUsage } from '../models/usage';

export const ANSWER: Answer = {
  summary: 'Apple’s revenue grew.',
  key_figures: [
    {
      label: 'Revenue',
      value: 416161000000,
      unit: 'USD',
      period: 'FY2025',
      source_url: 'https://www.sec.gov/apple-10k',
    },
    {
      label: 'Diluted EPS',
      value: 7.46,
      unit: 'USD per share',
      period: 'FY2025',
      source_url: 'https://www.sec.gov/apple-10k',
    },
  ],
  sources: ['https://www.sec.gov/apple-10k', 'https://data.sec.gov/apple-facts'],
  as_of: '2026-11-23T10:00:00Z',
  verified: true,
  disclaimer: 'AlphaDesk provides research, not financial advice.',
};

export const USAGE: RunUsage = {
  duration_seconds: 4.2,
  input_tokens: 3000,
  output_tokens: 180,
  total_tokens: 3180,
  estimated_cost_usd: 0.0041,
};

export const ANSWER_MESSAGE: AnswerMessage = { type: 'answer', answer: ANSWER, usage: USAGE };
