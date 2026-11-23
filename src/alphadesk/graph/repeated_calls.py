"""Stop a model that keeps asking a tool for something it already has.

A tool called again with the same arguments returns the same data, so a repeat is not
progress. The prompt says so, but a prompt only makes it likely. Faced with a question no
tool can answer, the model sometimes fetches the same thing over and over until the step
limit ends the run without an answer. So code enforces it, in two steps:

1. A repeat is not run. The model gets a `repeated_call` error as data, telling it to answer
   with what it has.
2. If it repeats again in another message, the data tools are taken away. The only tool
   left is the answer tool, so the next reply is an answer.

One repeat is allowed: if the data provider failed (`upstream_error`), the same call may be
made once more, because that failure may have cleared. Other errors would only happen again.

The step limit stays, as the last resort for loops that are not exact repeats.

Counting starts at the latest message in the user's role, which is either a new question or
the grounding check's feedback. Data from an earlier question may be out of date, so fetching
it again is right. And the history trim cuts only before such a message, so a result a model
is told it already has is always one it can still see.
"""

import json
import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain.tools.tool_node import ToolCallRequest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.types import Command
from pydantic import ValidationError

from alphadesk.domain.tool_results import ToolError
from alphadesk.graph.threads import ANSWER_TOOL

logger = logging.getLogger(__name__)

# How many model messages may contain a repeat before the data tools are taken away.
MAX_REPEAT_ROUNDS = 2

# How many times a call may run while its data provider keeps failing: the first try, and
# one retry. Each try can wait for a full timeout, so more would keep the user waiting.
MAX_RUNS_AFTER_FAILURE = 2


def repeated_call_ids(messages: Sequence[BaseMessage]) -> set[str | None]:
    """The IDs of this run's tool calls that repeat one already made with the same arguments.

    A retry that is allowed after a provider failure is not a repeat.

    Args:
        messages: The thread, oldest first. Only what follows the latest message in the
            user's role counts.
    """
    # The calls that were let through, by tool and arguments.
    runs: dict[tuple[str, str], list[str | None]] = {}
    failed: set[str | None] = set()
    repeated: set[str | None] = set()
    # In order, so a call is judged only by what was known when the model made it.
    for message in _current_run(messages):
        if isinstance(message, ToolMessage) and _provider_failed(message):
            failed.add(message.tool_call_id)
        if not isinstance(message, AIMessage):
            continue
        for call in message.tool_calls:
            if call["name"] == ANSWER_TOOL:
                continue  # Fetches nothing, so answering again is not a repeat.
            key = (call["name"], json.dumps(call["args"], sort_keys=True))
            earlier = runs.setdefault(key, [])
            if not earlier:
                earlier.append(call["id"])
            elif earlier[-1] in failed and len(earlier) < MAX_RUNS_AFTER_FAILURE:
                earlier.append(call["id"])  # The one allowed retry.
            else:
                repeated.add(call["id"])
    return repeated


def repeat_rounds(messages: Sequence[BaseMessage]) -> int:
    """How many of this run's model messages contained at least one repeated call."""
    repeated = repeated_call_ids(messages)
    return sum(
        isinstance(message, AIMessage)
        and any(call["id"] in repeated for call in message.tool_calls)
        for message in _current_run(messages)
    )


def _current_run(messages: Sequence[BaseMessage]) -> Sequence[BaseMessage]:
    """The messages after the latest one in the user's role."""
    for index in range(len(messages) - 1, -1, -1):
        if isinstance(messages[index], HumanMessage):
            return messages[index + 1 :]
    return messages


def _provider_failed(message: ToolMessage) -> bool:
    """True for a tool result saying the data provider failed, which may clear on a retry."""
    try:
        error = ToolError.model_validate_json(message.text)
    except ValidationError:
        return False  # Data, not an error.
    return error.error_type == "upstream_error"


class RepeatedToolCallMiddleware(AgentMiddleware):
    """Refuses repeated tool calls, and then takes the data tools away.

    Async only: the app always runs the agent with `astream`.
    """

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command[Any]]],
    ) -> ToolMessage | Command[Any]:
        """Run a tool call, unless it is a repeat. Not calling `handler` skips the tool."""
        call = request.tool_call
        if call["id"] not in repeated_call_ids(request.state["messages"]):
            return await handler(request)
        logger.info("Refused a repeated call to %s.", call["name"])
        error = ToolError(
            error_type="repeated_call",
            message=(
                f"You already called {call['name']} with these arguments, so it was not run "
                "again. Do not call it again. Answer now with what you have, and say plainly "
                "what the tools could not tell you."
            ),
            as_of=datetime.now(UTC),
        )
        return ToolMessage(error.model_dump_json(), name=call["name"], tool_call_id=call["id"])

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        """Call the model, without its data tools once it has repeated itself too often.

        `create_agent` adds the answer tool itself and makes the model call some tool, so
        with no other tools left it has to answer.
        """
        # From the state, not the request: another middleware may have trimmed the request.
        if repeat_rounds(request.state["messages"]) >= MAX_REPEAT_ROUNDS:
            logger.warning("The model keeps repeating tool calls. It must answer now.")
            request = request.override(tools=[])
        return await handler(request)
