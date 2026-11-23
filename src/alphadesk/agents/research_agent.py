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

Each run may call the model at most `max_model_calls` times. A model that keeps calling
tools without answering is stopped with `RunLimitError` instead of spending tokens
forever. The check runs before each model call, so a stopped thread never ends on a tool
call that has no result, and the next question on it works as normal.

Each turn also reports its `RunUsage`: time, tokens (as the provider counted them) and
estimated cost. It goes out in the `final` event, and is saved with the checked answer in the
thread, so a reloaded conversation shows exactly what was streamed (`graph/threads.py`).

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
import time
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any
from uuid import uuid4

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, ModelCallLimitMiddleware
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
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
from alphadesk.domain.errors import RunLimitError
from alphadesk.domain.thread import AnswerMessage
from alphadesk.domain.tool_results import ToolResult
from alphadesk.domain.usage import ModelPrice, RunUsage
from alphadesk.graph.history import TrimHistoryMiddleware
from alphadesk.graph.threads import ANSWER_TOOL, desk_message
from alphadesk.services.answers import finalise_answer
from alphadesk.services.filings import FilingsService
from alphadesk.services.financials import FinancialFactsService
from alphadesk.services.grounding import GroundingFailure, apply_grounding, check_grounding
from alphadesk.services.quotes import QuoteService
from alphadesk.services.usage import summarise_usage
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
        usage: Time, tokens and estimated cost of the whole turn, both attempts included.
    """

    answer: Answer
    messages: list[BaseMessage]
    usage: RunUsage


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
    max_model_calls: int,
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
        max_model_calls: The most model calls one run may make, from
            `Settings.agent_max_model_calls`. One more raises `RunLimitError`.
        checkpointer: Saves the state after every step, per thread, from
            `create_checkpointer`. Needed by `ask_research_agent`. Without one the agent
            forgets everything between calls.

    Returns:
        A compiled graph. `ask_research_agent` is the normal way to run it.
    """
    # Typed as the base class: each middleware adds its own fields to the state, and the
    # type checker cannot see that a list of different ones still fits `create_agent`.
    middleware: list[AgentMiddleware[Any, Any, Any]] = [
        # Counts model calls in this run and raises before one call too many. "error"
        # rather than "end": "end" would save a fake model message into the thread.
        ModelCallLimitMiddleware(run_limit=max_model_calls, exit_behavior="error"),
        # Trims what the model is sent, not what the checkpointer saves.
        TrimHistoryMiddleware(history_max_tokens),
    ]
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
        middleware=middleware,
        checkpointer=checkpointer,
        name="research_agent",
    )


async def ask_research_agent(
    agent: CompiledStateGraph, question: str, thread_id: str, *, price: ModelPrice
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
        price: The price of the agent's model, from `get_model_price`, for the usage.

    Returns:
        The grounded answer, every message of this turn and its usage.

    Raises:
        ValueError: The agent has no checkpointer, so it cannot hold a conversation.
        NoAnswerError: The agent finished without an `AnswerDraft`.
        RunLimitError: The agent reached its model call limit without answering.
    """
    run: ResearchRun | None = None
    async for item in _research_turn(agent, question, thread_id, price):
        if isinstance(item, ResearchRun):
            run = item
    if run is None:
        # `_research_turn` always ends with a ResearchRun or raises, so this means a bug.
        raise RuntimeError("The research turn ended without a result.")
    return run


async def stream_research_agent(
    agent: CompiledStateGraph, question: str, thread_id: str, *, price: ModelPrice
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
        price: The price of the agent's model, from `get_model_price`, for the usage.

    Yields:
        Progress events, then exactly one `FinalEvent` with the answer and its usage,
        which is always last.

    Raises:
        ValueError: The agent has no checkpointer.
        NoAnswerError: The agent finished without an `AnswerDraft`. Raised after any
            progress events already yielded.
        RunLimitError: The agent reached its model call limit. Raised the same way.
    """
    async for item in _research_turn(agent, question, thread_id, price):
        if isinstance(item, ResearchRun):
            yield FinalEvent(answer=item.answer, usage=item.usage)
        else:
            yield item


async def _research_turn(
    agent: CompiledStateGraph, question: str, thread_id: str, price: ModelPrice
) -> AsyncIterator[ProgressEvent | ResearchRun]:
    """One grounded turn: progress events as they happen, then the `ResearchRun`, last.

    Both public functions are built on this one, so the turn's logic is written once.
    """
    if not isinstance(agent.checkpointer, BaseCheckpointSaver):
        raise ValueError("The research agent needs a checkpointer to hold a conversation.")
    started = time.perf_counter()
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
        feedback = desk_message(_retry_prompt(failures))
        async for event in _stream_attempt(agent, feedback, config):
            yield event
        state = await _saved_state(agent, config)
        # This turn now spans both attempts, so the first attempt's tool results count too.
        turn = messages_since(state["messages"], question_message)
        answer = answer_from_agent_state(state, turn)
        failures = check_grounding(answer, tool_results_from_messages(turn))

    usage = summarise_usage(
        token_counts=_token_counts(turn),
        duration_seconds=time.perf_counter() - started,
        price=price,
    )
    if usage.total_tokens == 0 and any(isinstance(m, AIMessage) for m in turn):
        # A real model call never uses zero tokens, so the provider sent no usage. Missing
        # usage counts as zero so the answer still goes out, but it must not pass unseen.
        logger.warning("The model reported no token usage on thread %s; cost shows $0.", thread_id)
    answer = apply_grounding(answer, failures)
    await _save_answer(agent, config, turn, AnswerMessage(answer=answer, usage=usage))
    yield ResearchRun(answer=answer, messages=turn, usage=usage)


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

    Raises:
        RunLimitError: The model call limit was reached. LangChain's own error is turned
            into ours here, so `services/` can catch it without importing LangChain.
    """
    try:
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
    except ModelCallLimitExceededError as exc:
        raise RunLimitError(str(exc)) from exc


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
            if name == ANSWER_TOOL:
                continue  # Ends the run and fetches no data, so there is nothing to report.
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


def _token_counts(messages: Sequence[BaseMessage]) -> list[tuple[int, int]]:
    """`(input_tokens, output_tokens)` for each model reply in `messages`.

    The counts are the provider's own, attached to each reply as `usage_metadata`, so they
    match the trace and the bill. A reply without them (a provider that does not report
    usage) counts as zero rather than failing the run.
    """
    counts: list[tuple[int, int]] = []
    for message in messages:
        if isinstance(message, AIMessage) and message.usage_metadata is not None:
            usage = message.usage_metadata
            counts.append((usage["input_tokens"], usage["output_tokens"]))
    return counts


async def _save_answer(
    agent: CompiledStateGraph,
    config: RunnableConfig,
    turn: Sequence[BaseMessage],
    answer: AnswerMessage,
) -> None:
    """Save the turn's answer and usage in the thread, on the message that confirms the answer.

    They go in that `ToolMessage`'s `artifact`: a field LangChain keeps with the message,
    and so in the checkpoint, but never sends to the model. A reloaded conversation can
    then show each answer and what it cost, and the model's context is not touched.

    `aupdate_state` with a message that has an existing ID replaces that message rather
    than adding one (the `add_messages` reducer matches on ID).
    """
    confirmation = _last_answer_message(turn)
    if confirmation is None:
        return
    with_answer = confirmation.model_copy(update={"artifact": answer.model_dump(mode="json")})
    await agent.aupdate_state(config, {"messages": [with_answer]})


def _last_answer_message(messages: Sequence[BaseMessage]) -> ToolMessage | None:
    """The confirmation `ToolStrategy` added for the final answer tool call, if any."""
    for message in reversed(messages):
        if isinstance(message, ToolMessage) and message.name == ANSWER_TOOL:
            return message
    return None


def _retry_prompt(failures: Sequence[GroundingFailure]) -> str:
    """The message that tells the model which figures failed and why."""
    lines = [
        f'- "{failure.figure.label}" ({failure.figure.period}): {" ".join(failure.reasons)}'
        for failure in failures
    ]
    return _load_prompt(_RETRY_PROMPT_FILE).format(failures="\n".join(lines))
