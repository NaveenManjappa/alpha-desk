/** Mirrors `src/alphadesk/domain/thread.py`. Change both in the same commit. */

import { Answer } from './answer';
import { RunUsage } from './usage';

/** What the user asked. */
export interface QuestionMessage {
  type: 'question';
  text: string;
}

/** What the desk answered, and what the run used. */
export interface AnswerMessage {
  type: 'answer';
  answer: Answer;
  usage: RunUsage;
}

/** A discriminated union on `type`. Each type is shown by its own component. */
export type ThreadMessage = QuestionMessage | AnswerMessage;

/** The conversation `GET /threads/{id}` returns. */
export interface Thread {
  thread_id: string;
  messages: ThreadMessage[];
}

/** One line in the list `GET /threads` returns. */
export interface ThreadSummary {
  thread_id: string;
  title: string;
  last_used_at: string;
}
