"""The research agent: a model that can call tools in a loop until it can answer.

`create_agent` builds a small LangGraph graph with two nodes, "model" and "tools":

    model --(calls a data tool)--> tools --> model --(calls the answer tool)--> end

The agent answers with an `AnswerDraft`, not free text. `ToolStrategy` offers the model one
extra tool whose arguments are the `AnswerDraft` schema, and forces the model to call
*some* tool on every turn. Calling that answer tool ends the loop. If the arguments do not
fit the schema, the validation error goes back to the model and it tries again.

`answer_from_agent_state` then turns the draft into the full `Answer`, adding the fields
only code may set. `ask_research_agent` runs the whole thing: it asks, checks every key
figure against the tool results (the grounding check), and retries once if one fails.

The agent has a checkpointer, so it remembers. Each call to `ask_research_agent` names a
thread; LangGraph loads that thread's saved messages before the model runs and saves the
new ones after every step. Only the new question is sent in; the history comes from the
checkpoint.

The checkpoint keeps the whole thread, but each model call is sent only the most recent
part of it that fits the history budget (`graph/history.py`).

The agent runs with `astream`, so progress can be shown while it works.
`stream_research_agent` turns what the graph streams into chat events: a `status` event
each time the model decides to call a data tool, a `token` event for each piece of text the
model writes, and a `final` event with the grounded answer. `ask_research_agent` runs the
same stream and returns only the result.

This module decides what goes into that loop: which prompt, which tools and which output
type. It does not choose the model or create the tools' dependencies; the caller passes
them in.
"""

import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any
from uuid import uuid4

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph
from pydantic import TypeAdapter, ValidationError

from alphadesk.domain.answer import Answer, AnswerDraft, NoAnswerError
from alphadesk.domain.chat_events import FinalEvent, ProgressEvent, StatusEvent, TokenEvent
from alphadesk.domain.tool_results import ToolResult
from alphadesk.graph.history import TrimHistoryMiddleware
from alphadesk.services.answers import finalise_answer
from alphadesk.services.filings import FilingsService
from alphadesk.services.financials import FinancialFactsService
from alphadesk.services.grounding import GroundingFailure, apply_grounding, check_grounding
from alphadesk.services.quotes import QuoteService
from alphadesk.tools.filings_tool import make_list_recent_filings_tool
from alphadesk.tools.financial_facts_tool import make_get_financial_facts_tool
from alphadesk.tools.quote_tool import make_get_quote_tool

logger = logging.getLogger(__name__)

_PROMPT_FILE = "research_agent.md"
_RETRY_PROMPT_FILE = "grounding_retry.md"

# Parses a tool's JSON reply into whichever result type it fits. Built once: building a
# TypeAdapter compiles a validator, which is slow to repeat on every message.
_tool_result_adapter: TypeAdapter[ToolResult] = TypeAdapter(ToolResult)

# The names of the two nodes `create_agent` builds, as they appear in streamed metadata.
_MODEL_NODE = "model"

# `ToolStrategy` names the answer tool after the output class. Calling it ends the run; it
# fetches no data, so it gets no status event.
_ANSWER_TOOL = AnswerDraft.__name__

# What the user is shown when the model calls each data tool. A tool missing here still
# gets a status event, with a plain fallback message.
_TOOL_STATUS = {
    "get_quote": "Getting the latest share price",
    "get_financial_facts": "Reading reported financials from SEC EDGAR",
    "list_recent_filings": "Listing recent SEC filings",
}


@dataclass(frozen=True)
class ResearchRun:
    """The outcome of `ask_research_agent`.

    Attributes:
        answer: The grounded answer, with `verified` set by the grounding check.
        messages: Every message of this turn, from the question on, across both attempts
            if there was a retry. Earlier turns stay in the thread's checkpoint.
    """

    answer: Answer
    messages: list[BaseMessage]


def load_system_prompt() -> str:
    """Read the research agent's system prompt from `prompts/`."""
    return _load_prompt(_PROMPT_FILE)


def _load_prompt(name: str) -> str:
    """Read a prompt file from `prompts/`.

    `importlib.resources` finds the file inside the installed package, so this works
    from any working directory, not only the repo root.
    """
    return files("alphadesk").joinpath("prompts", name).read_text(encoding="utf-8")


def create_research_agent(
    model: BaseChatModel,
    quote_service: QuoteService,
    financial_facts_service: FinancialFactsService,
    filings_service: FilingsService,
    history_max_tokens: int,
    checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Build the research agent.

    Each service backs one tool and is passed in so tests can use a fake client.

    Args:
        model: The chat model, from `get_chat_model`. Passed in so tests can use a fake.
        quote_service: Backs `get_quote` (Finnhub).
        financial_facts_service: Backs `get_financial_facts` (SEC EDGAR).
        filings_service: Backs `list_recent_filings` (SEC EDGAR).
        history_max_tokens: The most history, in estimated tokens, sent on each model call,
            from `Settings.history_max_tokens`. Older turns are left out of the call but
            stay in the checkpoint.
        checkpointer: Saves the state after every step, per thread, from
            `create_checkpointer`. Needed by `ask_research_agent`. Without one the agent
            forgets everything between calls.

    Returns:
        A compiled graph. `ask_research_agent` is the normal way to run it.
    """
    return create_agent(
        model=model,
        tools=[
            make_get_quote_tool(quote_service),
            make_get_financial_facts_tool(financial_facts_service),
            make_list_recent_filings_tool(filings_service),
        ],
        system_prompt=load_system_prompt(),
        # ToolStrategy, chosen explicitly rather than letting LangChain pick from the
        # model's profile: it behaves the same for OpenAI, Azure OpenAI and the fake test
        # model, and a draft that fails validation is sent back to the model to fix
        # (handle_errors=True) instead of crashing the run.
        response_format=ToolStrategy(AnswerDraft, handle_errors=True),
        # Trims what the model is sent, not what the checkpointer saves.
        middleware=[TrimHistoryMiddleware(history_max_tokens)],
        checkpointer=checkpointer,
        name="research_agent",
    )


async def ask_research_agent(
    agent: CompiledStateGraph, question: str, thread_id: str
) -> ResearchRun:
    """Ask the agent a question on a thread and return an answer whose figures were checked.

    The thread's earlier turns come from the checkpointer, so a follow-up such as "And its
    revenue?" knows which company is meant.

    If any key figure fails the grounding check, the agent is asked once more on the same
    thread, with a message naming each failed figure and why. If the second answer still
    fails, its failed figures are removed and `verified` is False.

    The grounding check and `as_of` use only this turn's tool results. Data fetched for an
    earlier question may be stale, so every figure must be fetched again for this one.

    `stream_research_agent` runs the same turn but also reports progress as it goes.

    Args:
        agent: From `create_research_agent`, with a checkpointer.
        question: The user's question.
        thread_id: Names the conversation. Reuse it to continue; use a new one to start
            fresh.

    Returns:
        The grounded answer and every message of this turn.

    Raises:
        ValueError: The agent has no checkpointer, so it cannot hold a conversation.
        NoAnswerError: The agent finished without an `AnswerDraft`.
    """
    run: ResearchRun | None = None
    async for item in _research_turn(agent, question, thread_id):
        if isinstance(item, ResearchRun):
            run = item
    if run is None:
        # `_research_turn` always ends with a ResearchRun or raises, so this means a bug.
        raise RuntimeError("The research turn ended without a result.")
    return run


async def stream_research_agent(
    agent: CompiledStateGraph, question: str, thread_id: str
) -> AsyncIterator[ProgressEvent | FinalEvent]:
    """Ask the agent a question on a thread, yielding progress events, then the answer.

    The same turn as `ask_research_agent`, grounding retry included, but each step is
    reported as it happens: a `StatusEvent` when the model calls a data tool, a
    `TokenEvent` for any text the model writes, and finally one `FinalEvent` with the
    grounded answer. If the grounding check sends the agent round again, the events of
    both attempts are yielded, in order.

    Args:
        agent: From `create_research_agent`, with a checkpointer.
        question: The user's question.
        thread_id: Names the conversation. Reuse it to continue.

    Yields:
        Progress events, then exactly one `FinalEvent`, which is always last.

    Raises:
        ValueError: The agent has no checkpointer.
        NoAnswerError: The agent finished without an `AnswerDraft`. Raised after any
            progress events already yielded.
    """
    async for item in _research_turn(agent, question, thread_id):
        if isinstance(item, ResearchRun):
            yield FinalEvent(answer=item.answer)
        else:
            yield item


async def _research_turn(
    agent: CompiledStateGraph, question: str, thread_id: str
) -> AsyncIterator[ProgressEvent | ResearchRun]:
    """One grounded turn: progress events as they happen, then the `ResearchRun`, last.

    Both public functions are built on this one, so the turn's logic is written once.
    """
    if not isinstance(agent.checkpointer, BaseCheckpointSaver):
        raise ValueError("The research agent needs a checkpointer to hold a conversation.")
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    # Our own ID on the question, so this turn's messages can be found in the thread.
    question_message = HumanMessage(question, id=str(uuid4()))

    async for event in _stream_attempt(agent, question_message, config):
        yield event
    state = await _saved_state(agent, config)
    turn = messages_since(state["messages"], question_message)
    answer = answer_from_agent_state(state, turn)
    failures = check_grounding(answer, tool_results_from_messages(turn))

    if failures:
        logger.info("Retrying the research agent once after a failed grounding check.")
        # Only the feedback is sent: the first attempt is already saved on the thread.
        feedback = HumanMessage(_retry_prompt(failures))
        async for event in _stream_attempt(agent, feedback, config):
            yield event
        state = await _saved_state(agent, config)
        # This turn now spans both attempts, so the first attempt's tool results count too.
        turn = messages_since(state["messages"], question_message)
        answer = answer_from_agent_state(state, turn)
        failures = check_grounding(answer, tool_results_from_messages(turn))

    yield ResearchRun(answer=apply_grounding(answer, failures), messages=turn)


async def _stream_attempt(
    agent: CompiledStateGraph, message: HumanMessage, config: RunnableConfig
) -> AsyncIterator[ProgressEvent]:
    """Run the agent once on the thread with one new message, yielding progress events.

    Two stream modes run at once:

    - "messages" yields each piece of model output as the provider sends it, with metadata
      naming the graph node that produced it. Only text from the model node becomes a
      token; this mode also carries the tool messages, which are not for the user.
    - "updates" yields each node's output once the node finishes. When the model node
      finishes with tool calls, those tools run next, so that is the moment for a status.

    `version="v2"` makes every part a dict with `type`, `ns` and `data` keys, whichever
    modes are on. (LangGraph also offers `stream_events(version="v3")`, which its docs
    now recommend, but in the installed version it is marked experimental.)
    """
    async for part in agent.astream(
        {"messages": [message]},
        config,
        stream_mode=["messages", "updates"],
        version="v2",
    ):
        if part["type"] == "messages":
            chunk, metadata = part["data"]
            if (
                metadata.get("langgraph_node") == _MODEL_NODE
                and isinstance(chunk, AIMessageChunk)
                and chunk.text
            ):
                yield TokenEvent(text=chunk.text)
        elif part["type"] == "updates":
            for event in _status_events(part["data"]):
                yield event


def _status_events(update: dict[str, Any]) -> list[StatusEvent]:
    """A status event for each data tool the model just asked for, in the order asked.

    Args:
        update: One "updates" part's data: each node that finished, mapped to its output.
    """
    model_output = update.get(_MODEL_NODE)
    if not isinstance(model_output, dict):
        return []
    events: list[StatusEvent] = []
    for message in model_output.get("messages", []):
        if not isinstance(message, AIMessage):
            continue
        for call in message.tool_calls:
            name = call["name"]
            if name == _ANSWER_TOOL:
                continue
            status = _TOOL_STATUS.get(name, f"Running {name}")
            events.append(StatusEvent(tool=name, message=status))
    return events


async def _saved_state(agent: CompiledStateGraph, config: RunnableConfig) -> dict[str, Any]:
    """The thread's state as the checkpointer saved it at the end of the last run.

    `astream` yields progress, not the final state, so it is read back afterwards. It has
    the same `messages` and `structured_response` that `ainvoke` would have returned.
    """
    snapshot = await agent.aget_state(config)
    return snapshot.values


def answer_from_agent_state(
    state: dict[str, Any], turn_messages: Sequence[BaseMessage] | None = None
) -> Answer:
    """Build the `Answer` from the agent's finished state, before the grounding check.

    The model wrote the draft. Code adds `as_of` (from the tool results), the disclaimer,
    and `verified=False`; only `apply_grounding` may set it to True.

    Args:
        state: What `agent.ainvoke` returned.
        turn_messages: This turn's messages, whose tool results set `as_of`. Defaults to
            every message in the state, which is right when there are no earlier turns.

    Returns:
        The complete, validated `Answer`.

    Raises:
        NoAnswerError: The agent finished without an `AnswerDraft`. `create_agent` clears
            the previous turn's answer on every model call, so a turn that ends without
            one never returns an older answer.
    """
    draft = state.get("structured_response")
    if not isinstance(draft, AnswerDraft):
        raise NoAnswerError("The research agent finished without a structured answer.")
    messages = state["messages"] if turn_messages is None else turn_messages
    return finalise_answer(
        draft,
        data_fetched_at=[result.as_of for result in tool_results_from_messages(messages)],
        answered_at=datetime.now(UTC),
    )


def messages_since(messages: Sequence[BaseMessage], first: BaseMessage) -> list[BaseMessage]:
    """The messages from `first` (matched by ID) to the end: one turn of a thread.

    Raises:
        LookupError: No message has `first`'s ID.
    """
    for index, message in enumerate(messages):
        if message.id == first.id:
            return list(messages[index:])
    raise LookupError(f"Message {first.id} is not in this thread.")


def tool_results_from_messages(messages: Sequence[BaseMessage]) -> list[ToolResult]:
    """Every data tool result in the conversation, parsed back into its typed model.

    Tool results reach the agent as JSON text. Tool messages that are not a data tool's
    result, such as the answer tool's confirmation or a schema error sent back to the
    model, do not parse and are skipped. That matters: the confirmation repeats the
    model's own figures, and must never count as evidence for them.
    """
    results: list[ToolResult] = []
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        try:
            results.append(_tool_result_adapter.validate_json(message.text))
        except ValidationError:
            continue
    return results


def _retry_prompt(failures: Sequence[GroundingFailure]) -> str:
    """The message that tells the model which figures failed and why."""
    lines = [
        f'- "{failure.figure.label}" ({failure.figure.period}): {" ".join(failure.reasons)}'
        for failure in failures
    ]
    return _load_prompt(_RETRY_PROMPT_FILE).format(failures="\n".join(lines))
