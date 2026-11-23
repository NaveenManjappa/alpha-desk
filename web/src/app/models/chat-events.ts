/** Mirrors `src/alphadesk/domain/chat_events.py`. Change both in the same commit. */

import { Answer } from './answer';
import { RunUsage } from './usage';

/** A data tool is about to run. */
export interface StatusEvent {
  type: 'status';
  tool: string;
  message: string;
}

/** A piece of text the model wrote on the way to its answer. */
export interface TokenEvent {
  type: 'token';
  text: string;
}

/** The finished answer, and what the run used. Ends the stream. */
export interface FinalEvent {
  type: 'final';
  answer: Answer;
  usage: RunUsage;
}

/** The run could not finish. Ends the stream. The message is safe to show. */
export interface ErrorEvent {
  type: 'error';
  message: string;
}

/**
 * Every event a chat stream can contain. A discriminated union: checking `type` tells
 * TypeScript which of the four it is.
 */
export type ChatEvent = StatusEvent | TokenEvent | FinalEvent | ErrorEvent;
