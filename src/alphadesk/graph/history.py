"""What the model is sent of a thread's history: whole tool exchanges, under a token budget.

A thread's checkpoint keeps every message forever. Sending all of it on every model call
would make each call slower and dearer than the last, and a long enough chat would
eventually overflow the model's context window. So before each model call the oldest
messages are dropped from what the model *sees*.

The trim is transient. `TrimHistoryMiddleware` changes only the request sent to the
model (`request.override(messages=...)`); the checkpoint still holds the full thread. That
matters here: `ask_research_agent` finds this turn's messages and tool results in the saved
state, and Phase 4 will summarise the dropped messages rather than lose them.

The system prompt is not in the trimmed list: `create_agent` keeps it apart, in
`request.system_message`, and always sends it.

Trimming only ever cuts just before a `HumanMessage`. Everything after a question, up to
the next one, is kept or dropped together, so a tool result is never separated from the
tool call that asked for it. Providers reject a tool result whose call is missing.

They also reject a call whose result is missing. A run that is stopped while a tool works
(the browser is closed, the API goes down) leaves one in the thread for good, so without
`drop_unfinished_tool_calls` every later question on that thread would fail.
"""

import logging
from collections.abc import Awaitable, Callable, Sequence

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import AIMessage, AnyMessage, BaseMessage, HumanMessage, ToolMessage

# Imported from `utils` directly: the package re-exports them lazily, which hides their
# types from Pyright.
from langchain_core.messages.utils import count_tokens_approximately, trim_messages

logger = logging.getLogger(__name__)


def count_history_tokens(messages: Sequence[BaseMessage]) -> int:
    """Estimate the tokens in `messages`, the same way the trim does.

    An estimate (about four characters per token), not the provider's tokenizer: it is
    fast, needs no extra dependency and works for any model. The budget is a cost guard,
    not an exact limit, so leave headroom below the model's real context window.
    """
    return count_tokens_approximately(messages)


def drop_unfinished_tool_calls(messages: Sequence[AnyMessage]) -> list[AnyMessage]:
    """Leave out tool calls that never got their result, as a stopped run leaves them.

    A model message with several calls goes as a whole if any one is unfinished, and so do
    the results it did get. The question before it stays.

    Args:
        messages: The conversation, oldest first.

    Returns:
        The messages without half-done tool exchanges: the original ones, not copies.
    """
    finished = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
    unfinished = [
        m
        for m in messages
        if isinstance(m, AIMessage) and any(call["id"] not in finished for call in m.tool_calls)
    ]
    orphaned = {call["id"] for m in unfinished for call in m.tool_calls}
    return [
        m
        for m in messages
        if m not in unfinished and not (isinstance(m, ToolMessage) and m.tool_call_id in orphaned)
    ]


def trim_history(messages: Sequence[AnyMessage], max_tokens: int) -> list[AnyMessage]:
    """Keep the most recent messages that fit in `max_tokens`, starting at a question.

    If even the latest question and what followed it do not fit, they are kept anyway,
    over budget, and a warning is logged: without the question the model cannot answer.

    Args:
        messages: The conversation, oldest first, without the system prompt.
        max_tokens: The budget, as counted by `count_history_tokens`.

    Returns:
        A suffix of `messages`: the original list's messages, not copies.
    """
    kept = trim_messages(
        messages,
        max_tokens=max_tokens,
        token_counter=count_history_tokens,
        strategy="last",  # keep the newest, drop the oldest
        start_on="human",  # cut only before a question, never inside a tool exchange
        allow_partial=False,  # never cut a message in half
    )
    if kept:
        return kept  # pyright: ignore[reportReturnType]  # a suffix of `messages`

    latest_question = _index_of_latest_question(messages)
    if latest_question is None:
        return list(messages)
    current_turn = list(messages[latest_question:])
    logger.warning(
        "The current turn alone is about %d tokens, over the history budget of %d. "
        "Sending it untrimmed.",
        count_history_tokens(current_turn),
        max_tokens,
    )
    return current_turn


def _index_of_latest_question(messages: Sequence[BaseMessage]) -> int | None:
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            return index
    return None


class TrimHistoryMiddleware(AgentMiddleware):
    """Cuts what each model call is sent down to whole tool exchanges within the budget.

    The state is left alone.

    `create_agent` runs every middleware's `wrap_model_call` around each model call.
    This one swaps in the trimmed messages and passes the request on.
    """

    def __init__(self, max_tokens: int) -> None:
        """Args:
        max_tokens: The history budget, from `Settings.history_max_tokens`.
        """
        super().__init__()
        self.max_tokens = max_tokens

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """Sync version, used by `agent.invoke`."""
        return handler(self._trimmed(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Async version, used by `agent.ainvoke`, which is how the app runs the agent."""
        return await handler(self._trimmed(request))

    def _trimmed(self, request: ModelRequest) -> ModelRequest:
        kept = trim_history(drop_unfinished_tool_calls(request.messages), self.max_tokens)
        dropped = len(request.messages) - len(kept)
        if dropped:
            logger.debug(
                "Trimmed history: sending %d of %d messages (about %d tokens).",
                len(kept),
                len(request.messages),
                count_history_tokens(kept),
            )
        return request.override(messages=kept)
