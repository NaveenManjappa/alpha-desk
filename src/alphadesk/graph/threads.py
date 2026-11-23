"""Reading a thread back: from the saved messages to the conversation the user saw.

A thread's checkpoint holds every message of every turn: questions, tool calls, tool
results, drafts, and the feedback the grounding check sends. A user saw only questions and
finished answers. Two marks in the saved messages tell those apart:

- A finished answer is an `AnswerMessage`, saved in the `artifact` of the message that
  confirms the answer tool call. The draft in the thread is not used: it is what the model
  wrote before the grounding check, so it may hold figures that were then removed.
- A message our own code sent in the user's role carries `DESK_SOURCE` in
  `additional_kwargs`. LangChain marks its own summaries the same way.

Neither mark is sent to the model.
"""

import logging
from collections.abc import Sequence

from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph
from pydantic import ValidationError

from alphadesk.domain.answer import AnswerDraft
from alphadesk.domain.thread import AnswerMessage, QuestionMessage, Thread, ThreadMessage

logger = logging.getLogger(__name__)

# `ToolStrategy` names the answer tool after the output class.
ANSWER_TOOL = AnswerDraft.__name__

# Both the key and the value of the mark on messages our own code wrote.
_SOURCE_KEY = "source"
DESK_SOURCE = "alphadesk"


def desk_message(text: str) -> HumanMessage:
    """A message to the model from our own code, not from the user.

    It has the user's role, because the model must act on it, and a mark, so it is never
    shown as something the user said.
    """
    return HumanMessage(text, additional_kwargs={_SOURCE_KEY: DESK_SOURCE})


async def read_thread(agent: CompiledStateGraph, thread_id: str) -> Thread:
    """The conversation on a thread, from the agent's checkpointer.

    Args:
        agent: From `create_research_agent`, with a checkpointer.
        thread_id: Names the conversation.

    Returns:
        The thread. An unknown ID is an empty thread, not an error: a thread exists from
        its first message on, so "new" and "unknown" are the same thing.
    """
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    snapshot = await agent.aget_state(config)
    messages = thread_messages(snapshot.values.get("messages", []))
    return Thread(thread_id=thread_id, messages=messages)


def thread_messages(saved: Sequence[BaseMessage]) -> list[ThreadMessage]:
    """The questions and finished answers among a thread's saved messages, oldest first."""
    messages: list[ThreadMessage] = []
    for message in saved:
        if isinstance(message, HumanMessage):
            if message.additional_kwargs.get(_SOURCE_KEY) != DESK_SOURCE:
                messages.append(QuestionMessage(text=message.text))
        elif isinstance(message, ToolMessage) and message.name == ANSWER_TOOL:
            answer = _saved_answer(message)
            if answer is not None:
                messages.append(answer)
    return messages


def _saved_answer(message: ToolMessage) -> AnswerMessage | None:
    """The answer saved on an answer tool's confirmation, or None if there is none."""
    if message.artifact is None:
        return None  # A draft that was not the last word: rejected, or sent back.
    try:
        return AnswerMessage.model_validate(message.artifact)
    except ValidationError:
        # One unreadable answer must not hide the rest of the conversation.
        logger.warning("Saved answer %s could not be read and was left out.", message.id)
        return None
