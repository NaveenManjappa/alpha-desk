"""Run one golden case through the real research agent and keep what the checks need."""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from uuid import uuid4

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph.state import CompiledStateGraph

from alphadesk.agents.research_agent import ask_research_agent
from alphadesk.domain.answer import Answer, AnswerDraft, NoAnswerError
from alphadesk.domain.errors import RunLimitError
from alphadesk.domain.usage import ModelPrice, RunUsage
from evals.dataset import GoldenCase

logger = logging.getLogger(__name__)

# `ToolStrategy` names the answer tool after the output class. It fetches no data.
_ANSWER_TOOL = AnswerDraft.__name__

# Each step in the results file is cut to this many characters. Enough to read a tool
# error or the start of a tool result; a full result is in the LangSmith trace.
_STEP_MAX_CHARS = 300


@dataclass(frozen=True)
class CaseRun:
    """What the agent did on the checked turn of one case.

    Attributes:
        answer: The grounded answer, or None if the run ended without one.
        tools_called: The data tools called in that turn, in order.
        steps: One line per message of that turn, for reading what went wrong. Kept
            even when the run ended without an answer.
        usage: Time, tokens and cost of that turn, or None without an answer.
        error: Why there is no answer, or None.
    """

    answer: Answer | None
    tools_called: list[str]
    steps: list[str]
    usage: RunUsage | None
    error: str | None = None


async def run_case(agent: CompiledStateGraph, case: GoldenCase, price: ModelPrice) -> CaseRun:
    """Ask the case's setup questions, then its question, on a new thread.

    The setup turns are not checked; they only give the question a history to rely on.
    A run that ends without an answer becomes a `CaseRun` with `error` set, so one bad
    case is recorded and scored instead of stopping the whole eval.
    """
    thread_id = f"eval-{case.id}-{uuid4().hex[:8]}"
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
    for earlier in case.setup:
        await ask_research_agent(agent, earlier, thread_id, price=price)
    # Where the checked turn starts in the thread, so its messages can be read back even
    # if the run fails. Every step is checkpointed, so a stopped run's steps are saved.
    turn_start = len(await _thread_messages(agent, config))
    try:
        run = await ask_research_agent(agent, case.question, thread_id, price=price)
    except (NoAnswerError, RunLimitError) as exc:
        logger.warning("Eval case %s ended without an answer: %s", case.id, exc)
        turn = (await _thread_messages(agent, config))[turn_start:]
        return CaseRun(
            answer=None,
            tools_called=tools_called(turn),
            steps=describe_steps(turn),
            usage=None,
            error=str(exc),
        )
    return CaseRun(
        answer=run.answer,
        tools_called=tools_called(run.messages),
        steps=describe_steps(run.messages),
        usage=run.usage,
    )


async def _thread_messages(agent: CompiledStateGraph, config: RunnableConfig) -> list[BaseMessage]:
    """Every message saved on the thread so far; empty for a new thread."""
    snapshot = await agent.aget_state(config)
    return list(snapshot.values.get("messages", []))


def tools_called(messages: Sequence[BaseMessage]) -> list[str]:
    """The data tools the model called in these messages, in order, repeats included.

    The answer tool is left out: it ends the run and fetches no data.
    """
    return [
        call["name"]
        for message in messages
        if isinstance(message, AIMessage)
        for call in message.tool_calls
        if call["name"] != _ANSWER_TOOL
    ]


def describe_steps(messages: Sequence[BaseMessage]) -> list[str]:
    """One short line per message: what the model asked for, and what each tool replied.

    The answer tool is included here, unlike in `tools_called`: a model that keeps
    sending an answer that fails validation shows up as repeated answer-tool steps.
    """
    steps: list[str] = []
    for message in messages:
        if isinstance(message, AIMessage) and message.tool_calls:
            calls = ", ".join(f"{call['name']}({call['args']})" for call in message.tool_calls)
            line = f"model -> {calls}"
        elif isinstance(message, AIMessage):
            line = f"model -> text: {message.text}"
        elif isinstance(message, ToolMessage):
            line = f"tool {message.name} -> {message.text}"
        else:
            line = f"{message.type} -> {message.text}"
        steps.append(line[:_STEP_MAX_CHARS])
    return steps
