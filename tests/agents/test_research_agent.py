"""Tests for the research agent loop. No real LLM and no network: a scripted fake model
plays the LLM, and the real tools, services and clients sit on in-memory httpx transports."""

from collections.abc import Iterator, Sequence
from typing import Any

import httpx
import pytest
from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import Field

from alphadesk.agents.research_agent import create_research_agent, load_system_prompt
from alphadesk.integrations.finnhub import FinnhubClient
from alphadesk.integrations.sec_edgar import EdgarClient, RateLimiter
from alphadesk.services.filings import FilingsService
from alphadesk.services.financials import FinancialFactsService
from alphadesk.services.quotes import QuoteService


class ScriptedChatModel(GenericFakeChatModel):
    """Replies with the given messages in order, and records what it was sent each turn.

    `create_agent` calls `bind_tools` to tell the model about the tools. A real model sends
    those tool schemas to the provider; the fake already knows its replies, so it ignores them.
    """

    calls: list[list[BaseMessage]] = Field(default_factory=list)
    tool_names: list[str] = Field(default_factory=list)

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "ScriptedChatModel":
        self.tool_names = [tool.name for tool in tools]
        return self

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> Any:
        self.calls.append(list(messages))
        return super()._generate(messages, *args, **kwargs)


def _model(*replies: AIMessage) -> ScriptedChatModel:
    script: Iterator[AIMessage] = iter(replies)
    return ScriptedChatModel(messages=script)


def _quote_service() -> QuoteService:
    apple = httpx.Response(200, json={"c": 227.5, "d": 1.25, "dp": 0.55, "t": 1_762_966_800})
    http = httpx.AsyncClient(
        base_url="https://finnhub.io/api/v1",
        transport=httpx.MockTransport(lambda _: apple),
    )
    return QuoteService(FinnhubClient(http))


def _agent(model: ScriptedChatModel) -> Any:
    """The agent with all three tools. EDGAR is never reached in these tests: it answers 503."""
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(503)))
    edgar = EdgarClient(http, RateLimiter(max_per_second=1000))
    return create_research_agent(
        model,
        quote_service=_quote_service(),
        financial_facts_service=FinancialFactsService(edgar),
        filings_service=FilingsService(edgar),
    )


def _ask(question: str) -> dict[str, Any]:
    return {"messages": [HumanMessage(question)]}


ASK_FOR_QUOTE = AIMessage(
    content="",
    tool_calls=[{"name": "get_quote", "args": {"ticker": "AAPL"}, "id": "call-1"}],
)


@pytest.mark.unit
def test_system_prompt_comes_from_the_prompts_folder() -> None:
    prompt = load_system_prompt()

    assert "get_quote" in prompt
    assert "get_financial_facts" in prompt
    assert "list_recent_filings" in prompt
    assert "not financial advice" in prompt


@pytest.mark.unit
@pytest.mark.asyncio
async def test_price_question_runs_model_then_tool_then_model() -> None:
    model = _model(ASK_FOR_QUOTE, AIMessage("Apple trades at $227.50."))
    agent = _agent(model)

    result = await agent.ainvoke(_ask("What is Apple's share price?"))

    messages = result["messages"]
    assert [type(m) for m in messages] == [HumanMessage, AIMessage, ToolMessage, AIMessage]
    assert '"price": 227.5' in messages[2].text
    assert messages[-1].text == "Apple trades at $227.50."
    # The model was called twice, and the second time it could read the tool's result.
    assert len(model.calls) == 2
    assert isinstance(model.calls[1][-1], ToolMessage)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_model_receives_the_system_prompt_first() -> None:
    model = _model(AIMessage("4"))
    agent = _agent(model)

    await agent.ainvoke(_ask("What is 2 plus 2?"))

    first_message = model.calls[0][0]
    assert isinstance(first_message, SystemMessage)
    assert first_message.text == load_system_prompt()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reply_without_tool_calls_ends_the_loop_after_one_model_call() -> None:
    model = _model(AIMessage("4"))
    agent = _agent(model)

    result = await agent.ainvoke(_ask("What is 2 plus 2?"))

    assert [type(m) for m in result["messages"]] == [HumanMessage, AIMessage]
    assert len(model.calls) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_model_is_offered_all_three_tools() -> None:
    model = _model(AIMessage("4"))

    await _agent(model).ainvoke(_ask("What is 2 plus 2?"))

    assert sorted(model.tool_names) == ["get_financial_facts", "get_quote", "list_recent_filings"]
