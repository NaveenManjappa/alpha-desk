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

This module decides what goes into that loop: which prompt, which tools and which output
type. It does not choose the model or create the tools' dependencies; the caller passes
them in.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, ToolMessage
from langgraph.graph.state import CompiledStateGraph
from pydantic import TypeAdapter, ValidationError

from alphadesk.domain.answer import Answer, AnswerDraft
from alphadesk.domain.tool_results import ToolResult
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


class NoAnswerError(Exception):
    """The agent stopped without producing an `AnswerDraft`, for example after a refusal."""


@dataclass(frozen=True)
class ResearchRun:
    """The outcome of `ask_research_agent`.

    Attributes:
        answer: The grounded answer, with `verified` set by the grounding check.
        messages: Every message in the run, across both attempts if there was a retry.
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
) -> CompiledStateGraph:
    """Build the research agent.

    Each service backs one tool and is passed in so tests can use a fake client.

    Args:
        model: The chat model, from `get_chat_model`. Passed in so tests can use a fake.
        quote_service: Backs `get_quote` (Finnhub).
        financial_facts_service: Backs `get_financial_facts` (SEC EDGAR).
        filings_service: Backs `list_recent_filings` (SEC EDGAR).

    Returns:
        A compiled graph. Run it with
        `await agent.ainvoke({"messages": [{"role": "user", "content": question}]})`,
        then pass the result to `answer_from_agent_state`.
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
        name="research_agent",
    )


async def ask_research_agent(agent: CompiledStateGraph, question: str) -> ResearchRun:
    """Ask the agent a question and return an answer whose figures have been checked.

    If any key figure fails the grounding check, the agent is asked once more, with the
    same conversation plus a message naming each failed figure and why. If the second
    answer still fails, its failed figures are removed and `verified` is False.

    Args:
        agent: From `create_research_agent`.
        question: The user's question.

    Returns:
        The grounded answer and every message of the run.

    Raises:
        NoAnswerError: The agent finished without an `AnswerDraft`.
    """
    state = await agent.ainvoke({"messages": [HumanMessage(question)]})
    answer = answer_from_agent_state(state)
    failures = check_grounding(answer, tool_results_from_messages(state["messages"]))

    if failures:
        logger.info("Retrying the research agent once after a failed grounding check.")
        feedback = HumanMessage(_retry_prompt(failures))
        state = await agent.ainvoke({"messages": [*state["messages"], feedback]})
        answer = answer_from_agent_state(state)
        # The retry's messages include the first attempt's, so its tool results count too.
        failures = check_grounding(answer, tool_results_from_messages(state["messages"]))

    return ResearchRun(answer=apply_grounding(answer, failures), messages=state["messages"])


def answer_from_agent_state(state: dict[str, Any]) -> Answer:
    """Build the `Answer` from the agent's finished state, before the grounding check.

    The model wrote the draft. Code adds `as_of` (from the tool results), the disclaimer,
    and `verified=False`; only `apply_grounding` may set it to True.

    Args:
        state: What `agent.ainvoke` returned.

    Returns:
        The complete, validated `Answer`.

    Raises:
        NoAnswerError: The agent finished without an `AnswerDraft`.
    """
    draft = state.get("structured_response")
    if not isinstance(draft, AnswerDraft):
        raise NoAnswerError("The research agent finished without a structured answer.")
    return finalise_answer(
        draft,
        data_fetched_at=[result.as_of for result in tool_results_from_messages(state["messages"])],
        answered_at=datetime.now(UTC),
    )


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
