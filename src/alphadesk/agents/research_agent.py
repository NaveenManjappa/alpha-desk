"""The research agent: a model that can call tools in a loop until it can answer.

`create_agent` builds a small LangGraph graph with two nodes, "model" and "tools":

    model --(calls a data tool)--> tools --> model --(calls the answer tool)--> end

The agent answers with an `AnswerDraft`, not free text. `ToolStrategy` offers the model one
extra tool whose arguments are the `AnswerDraft` schema, and forces the model to call
*some* tool on every turn. Calling that answer tool ends the loop. If the arguments do not
fit the schema, the validation error goes back to the model and it tries again.

`answer_from_agent_state` then turns the draft into the full `Answer`, adding the fields
only code may set.

This module decides what goes into that loop: which prompt, which tools and which output
type. It does not choose the model or create the tools' dependencies; the caller passes
them in.
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from importlib.resources import files
from typing import Any

from langchain.agents import create_agent
from langchain.agents.structured_output import ToolStrategy
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, ToolMessage
from langgraph.graph.state import CompiledStateGraph
from pydantic import AwareDatetime, BaseModel, ValidationError

from alphadesk.domain.answer import Answer, AnswerDraft
from alphadesk.services.answers import finalise_answer
from alphadesk.services.filings import FilingsService
from alphadesk.services.financials import FinancialFactsService
from alphadesk.services.quotes import QuoteService
from alphadesk.tools.filings_tool import make_list_recent_filings_tool
from alphadesk.tools.financial_facts_tool import make_get_financial_facts_tool
from alphadesk.tools.quote_tool import make_get_quote_tool

_PROMPT_FILE = "research_agent.md"


class NoAnswerError(Exception):
    """The agent stopped without producing an `AnswerDraft`, for example after a refusal."""


class _Timestamped(BaseModel):
    """The one field every data tool result shares. Other fields are ignored."""

    as_of: AwareDatetime


def load_system_prompt() -> str:
    """Read the research agent's system prompt from `prompts/`.

    `importlib.resources` finds the file inside the installed package, so this works
    from any working directory, not only the repo root.
    """
    return files("alphadesk").joinpath("prompts", _PROMPT_FILE).read_text(encoding="utf-8")


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


def answer_from_agent_state(state: dict[str, Any]) -> Answer:
    """Build the final `Answer` from the agent's finished state.

    The model wrote the draft. Code adds `as_of` (from the tool results), `verified`
    and the disclaimer.

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
        data_fetched_at=_tool_fetch_times(state["messages"]),
        answered_at=datetime.now(UTC),
    )


def _tool_fetch_times(messages: Sequence[BaseMessage]) -> list[datetime]:
    """The `as_of` time of every tool result that has one.

    Tool results reach the agent as JSON text. Messages without an `as_of`, such as the
    answer tool's own confirmation, are skipped.
    """
    times: list[datetime] = []
    for message in messages:
        if not isinstance(message, ToolMessage):
            continue
        try:
            times.append(_Timestamped.model_validate_json(message.text).as_of)
        except ValidationError:
            continue
    return times
