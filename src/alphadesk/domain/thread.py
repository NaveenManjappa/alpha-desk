"""Conversations, as the API returns them: one in full, or a line in the list.

A `Thread` is what the user would have seen. Not the saved messages themselves: those
also hold tool calls, tool results and the grounding check's feedback, which are the
agent's working notes.

Each message has a `type`, so a client can pick how to show it. A new kind of result in a
later phase is a new type here. The TypeScript models in `web/` mirror these classes; change
both together.
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from alphadesk.domain.answer import Answer
from alphadesk.domain.usage import RunUsage


class QuestionMessage(BaseModel):
    """What the user asked."""

    type: Literal["question"] = "question"
    text: str


class AnswerMessage(BaseModel):
    """What the desk answered, and what the run used. The same pair as the `final` event.

    Also the shape the agent saves in the thread, so a reloaded answer is exactly the one
    that was streamed, `verified` included, with nothing worked out again.
    """

    type: Literal["answer"] = "answer"
    answer: Answer
    usage: RunUsage


ThreadMessage = QuestionMessage | AnswerMessage


class Thread(BaseModel):
    """One conversation.

    Attributes:
        thread_id: Names the conversation.
        messages: Oldest first. Empty for a thread nobody has used. A question whose run
            failed or was cut off has no answer after it.
    """

    thread_id: str
    messages: list[ThreadMessage]


class ThreadSummary(BaseModel):
    """One line in the list of conversations, as `GET /threads` returns it.

    Attributes:
        thread_id: Names the conversation.
        title: Its first question, cut to length.
        last_used_at: When its last turn started.
    """

    thread_id: str
    title: str
    last_used_at: datetime
