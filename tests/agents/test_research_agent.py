"""Tests for the research agent loop. No real LLM and no network: a scripted fake model
plays the LLM, the real tools, services and clients sit on in-memory httpx transports, and
the checkpointer keeps its state in memory."""

import json
from collections.abc import Iterator, Sequence
from datetime import datetime
from typing import Any

import httpx
import pytest
from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from pydantic import Field

from alphadesk.agents.research_agent import (
    NoAnswerError,
    answer_from_agent_state,
    ask_research_agent,
    create_research_agent,
    load_system_prompt,
)
from alphadesk.domain.answer import DISCLAIMER, Answer, AnswerDraft
from alphadesk.graph.checkpointer import create_checkpointer
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


def _agent(model: ScriptedChatModel, checkpointer: BaseCheckpointSaver | None = None) -> Any:
    """The agent with all three tools. EDGAR is never reached in these tests: it answers 503."""
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(503)))
    edgar = EdgarClient(http, RateLimiter(max_per_second=1000))
    return create_research_agent(
        model,
        quote_service=_quote_service(),
        financial_facts_service=FinancialFactsService(edgar),
        filings_service=FilingsService(edgar),
        checkpointer=checkpointer,
    )


def _chat_agent(model: ScriptedChatModel) -> Any:
    """The agent with a checkpointer, as `ask_research_agent` needs it."""
    return _agent(model, create_checkpointer())


def _ask(question: str) -> dict[str, Any]:
    return {"messages": [HumanMessage(question)]}


ASK_FOR_QUOTE = AIMessage(
    content="",
    tool_calls=[{"name": "get_quote", "args": {"ticker": "AAPL"}, "id": "call-1"}],
)

APPLE_PRICE = {
    "label": "Share price",
    "value": 227.5,
    "unit": "USD",
    "period": "2025-11-12 16:20 UTC",
    "source_url": "https://finnhub.io/api/v1/quote?symbol=AAPL",
}


def _answer_call(call_id: str = "answer-1", **args: Any) -> AIMessage:
    """The model's final turn: a call to the answer tool `ToolStrategy` added."""
    return AIMessage(
        content="",
        tool_calls=[{"name": "AnswerDraft", "args": args, "id": call_id}],
    )


APPLE_ANSWER = _answer_call(
    summary="Apple's shares are up slightly today.",
    key_figures=[APPLE_PRICE],
    sources=[APPLE_PRICE["source_url"]],
)
FOUR = _answer_call(summary="Two plus two is four.", key_figures=[], sources=[])


@pytest.mark.unit
def test_system_prompt_comes_from_the_prompts_folder() -> None:
    prompt = load_system_prompt()

    assert "get_quote" in prompt
    assert "get_financial_facts" in prompt
    assert "list_recent_filings" in prompt
    assert "key_figures" in prompt


@pytest.mark.unit
@pytest.mark.asyncio
async def test_price_question_runs_model_then_tool_then_model() -> None:
    model = _model(ASK_FOR_QUOTE, APPLE_ANSWER)
    agent = _agent(model)

    result = await agent.ainvoke(_ask("What is Apple's share price?"))

    messages = result["messages"]
    # The final ToolMessage is LangChain confirming the answer tool call, not a data tool.
    assert [type(m) for m in messages] == [
        HumanMessage,
        AIMessage,
        ToolMessage,
        AIMessage,
        ToolMessage,
    ]
    assert '"price": 227.5' in messages[2].text
    # The model was called twice, and the second time it could read the tool's result.
    assert len(model.calls) == 2
    assert isinstance(model.calls[1][-1], ToolMessage)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_model_receives_the_system_prompt_first() -> None:
    model = _model(FOUR)
    agent = _agent(model)

    await agent.ainvoke(_ask("What is 2 plus 2?"))

    first_message = model.calls[0][0]
    assert isinstance(first_message, SystemMessage)
    assert first_message.text == load_system_prompt()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_answering_directly_ends_the_loop_after_one_model_call() -> None:
    model = _model(FOUR)
    agent = _agent(model)

    result = await agent.ainvoke(_ask("What is 2 plus 2?"))

    assert [type(m) for m in result["messages"]] == [HumanMessage, AIMessage, ToolMessage]
    assert len(model.calls) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_model_is_offered_the_three_data_tools_and_the_answer_tool() -> None:
    model = _model(FOUR)

    await _agent(model).ainvoke(_ask("What is 2 plus 2?"))

    assert sorted(model.tool_names) == [
        "AnswerDraft",
        "get_financial_facts",
        "get_quote",
        "list_recent_filings",
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_price_question_returns_a_typed_answer_with_code_set_fields() -> None:
    result = await _agent(_model(ASK_FOR_QUOTE, APPLE_ANSWER)).ainvoke(
        _ask("What is Apple's share price?")
    )

    answer = answer_from_agent_state(result)

    assert isinstance(answer, Answer)
    assert answer.summary == "Apple's shares are up slightly today."
    figure = answer.key_figures[0]
    assert (figure.label, figure.value, figure.unit) == ("Share price", 227.5, "USD")
    assert figure.source_url == APPLE_PRICE["source_url"]
    assert answer.disclaimer == DISCLAIMER
    assert answer.verified is False
    # as_of is the moment the quote tool fetched its data, read from the tool result.
    quote_fetched_at = json.loads(result["messages"][2].text)["as_of"]
    assert answer.as_of == datetime.fromisoformat(quote_fetched_at)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_disclaimer_from_the_model_is_ignored() -> None:
    model = _model(
        _answer_call(summary="Buy now.", key_figures=[], sources=[], disclaimer="Guaranteed!")
    )

    answer = answer_from_agent_state(await _agent(model).ainvoke(_ask("Should I buy?")))

    assert answer.disclaimer == DISCLAIMER


@pytest.mark.unit
@pytest.mark.asyncio
async def test_answer_that_breaks_the_schema_is_sent_back_and_retried() -> None:
    no_source = {key: value for key, value in APPLE_PRICE.items() if key != "source_url"}
    bad_answer = _answer_call(
        call_id="answer-bad", summary="Apple is up.", key_figures=[no_source], sources=[]
    )
    model = _model(ASK_FOR_QUOTE, bad_answer, APPLE_ANSWER)

    result = await _agent(model).ainvoke(_ask("What is Apple's share price?"))

    # The model saw the validation error naming the missing field, then answered again.
    assert len(model.calls) == 3
    error_message = model.calls[2][-1]
    assert isinstance(error_message, ToolMessage)
    assert "source_url" in error_message.text
    assert answer_from_agent_state(result).key_figures[0].source_url == APPLE_PRICE["source_url"]


@pytest.mark.unit
def test_state_without_a_structured_answer_raises() -> None:
    state = {"messages": [HumanMessage("Hi"), AIMessage("I can't help with that.")]}

    with pytest.raises(NoAnswerError):
        answer_from_agent_state(state)


# --- Grounding check and retry (Slice 7) ------------------------------------------------

INVENTED_CHANGE = {**APPLE_PRICE, "label": "Change today", "value": 9.99}
ANSWER_WITH_INVENTED_CHANGE = _answer_call(
    call_id="answer-invented",
    summary="Apple's shares jumped today.",
    key_figures=[APPLE_PRICE, INVENTED_CHANGE],
    sources=[APPLE_PRICE["source_url"]],
)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_grounded_answer_is_verified_without_a_retry() -> None:
    model = _model(ASK_FOR_QUOTE, APPLE_ANSWER)

    run = await ask_research_agent(_chat_agent(model), "What is Apple's share price?", "t1")

    assert run.answer.verified is True
    assert [figure.value for figure in run.answer.key_figures] == [227.5]
    assert len(model.calls) == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_failed_figure_is_sent_back_once_and_the_fixed_answer_is_verified() -> None:
    model = _model(ASK_FOR_QUOTE, ANSWER_WITH_INVENTED_CHANGE, APPLE_ANSWER)

    run = await ask_research_agent(_chat_agent(model), "What is Apple's share price?", "t1")

    # The retry turn told the model which figure failed and why.
    feedback = model.calls[2][-1]
    assert isinstance(feedback, HumanMessage)
    assert "Change today" in feedback.text
    assert "9.99" in feedback.text
    assert run.answer.verified is True
    assert run.answer.summary == "Apple's shares are up slightly today."


@pytest.mark.unit
@pytest.mark.asyncio
async def test_figure_that_fails_twice_is_removed_and_answer_unverified() -> None:
    second_try = ANSWER_WITH_INVENTED_CHANGE.model_copy(
        update={"tool_calls": [{**ANSWER_WITH_INVENTED_CHANGE.tool_calls[0], "id": "answer-2"}]}
    )
    model = _model(ASK_FOR_QUOTE, ANSWER_WITH_INVENTED_CHANGE, second_try)

    run = await ask_research_agent(_chat_agent(model), "What is Apple's share price?", "t1")

    assert len(model.calls) == 3  # one retry, no more
    assert run.answer.verified is False
    assert [figure.label for figure in run.answer.key_figures] == ["Share price"]
    # The messages cover both attempts, so the whole run can be inspected.
    assert isinstance(run.messages[0], HumanMessage)
    assert run.messages[-1].type == "tool"


# --- Conversation memory (Slice 8) ------------------------------------------------------


def _quote_call(call_id: str) -> AIMessage:
    """A fresh `get_quote` call. Each turn needs its own message: one thread holds them all."""
    return AIMessage(
        content="",
        tool_calls=[{"name": "get_quote", "args": {"ticker": "AAPL"}, "id": call_id}],
    )


def _apple_answer(call_id: str) -> AIMessage:
    return _answer_call(
        call_id=call_id,
        summary="Apple's shares are up slightly today.",
        key_figures=[APPLE_PRICE],
        sources=[APPLE_PRICE["source_url"]],
    )


def _texts(messages: Sequence[BaseMessage]) -> list[str]:
    return [message.text for message in messages]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_follow_up_on_the_same_thread_sees_the_earlier_turn() -> None:
    model = _model(_quote_call("q1"), _apple_answer("a1"), _quote_call("q2"), _apple_answer("a2"))
    agent = _chat_agent(model)

    await ask_research_agent(agent, "How is Apple doing?", thread_id="apple")
    await ask_research_agent(agent, "And its price again?", thread_id="apple")

    # The model's first call of turn two (call index 2) includes turn one's question.
    second_turn = _texts(model.calls[2])
    assert "How is Apple doing?" in second_turn
    assert second_turn[-1] == "And its price again?"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_new_thread_starts_with_no_memory() -> None:
    model = _model(_quote_call("q1"), _apple_answer("a1"), FOUR)
    agent = _chat_agent(model)

    await ask_research_agent(agent, "How is Apple doing?", thread_id="apple")
    await ask_research_agent(agent, "What is 2 plus 2?", thread_id="other")

    other_thread = _texts(model.calls[2])
    assert "How is Apple doing?" not in other_thread
    assert other_thread[-1] == "What is 2 plus 2?"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_saved_state_for_a_thread_can_be_read_back() -> None:
    agent = _chat_agent(_model(_quote_call("q1"), _apple_answer("a1")))

    await ask_research_agent(agent, "How is Apple doing?", thread_id="apple")
    snapshot = await agent.aget_state({"configurable": {"thread_id": "apple"}})

    messages = snapshot.values["messages"]
    assert [type(m) for m in messages] == [
        HumanMessage,
        AIMessage,
        ToolMessage,
        AIMessage,
        ToolMessage,
    ]
    assert messages[0].text == "How is Apple doing?"
    # The answer was saved too, and came back out of the checkpoint as an AnswerDraft.
    assert isinstance(snapshot.values["structured_response"], AnswerDraft)
    assert snapshot.next == ()  # finished: no step is waiting to run


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_messages_hold_only_this_turn() -> None:
    model = _model(_quote_call("q1"), _apple_answer("a1"), _quote_call("q2"), _apple_answer("a2"))
    agent = _chat_agent(model)

    await ask_research_agent(agent, "How is Apple doing?", thread_id="apple")
    run = await ask_research_agent(agent, "And its price again?", thread_id="apple")

    assert run.messages[0].text == "And its price again?"
    assert len(run.messages) == 5


@pytest.mark.unit
@pytest.mark.asyncio
async def test_data_from_an_earlier_turn_does_not_ground_a_new_answer() -> None:
    # Turn two copies the price from turn one without fetching it again, twice.
    model = _model(_quote_call("q1"), _apple_answer("a1"), _apple_answer("a2"), _apple_answer("a3"))
    agent = _chat_agent(model)

    await ask_research_agent(agent, "How is Apple doing?", thread_id="apple")
    run = await ask_research_agent(agent, "And its price again?", thread_id="apple")

    assert run.answer.verified is False
    assert run.answer.key_figures == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_turn_without_an_answer_never_returns_the_previous_answer() -> None:
    model = _model(_quote_call("q1"), _apple_answer("a1"), AIMessage("I can't help with that."))
    agent = _chat_agent(model)

    await ask_research_agent(agent, "How is Apple doing?", thread_id="apple")

    with pytest.raises(NoAnswerError):
        await ask_research_agent(agent, "Tell me a secret.", thread_id="apple")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_asking_an_agent_without_a_checkpointer_is_refused() -> None:
    with pytest.raises(ValueError, match="checkpointer"):
        await ask_research_agent(_agent(_model(FOUR)), "What is 2 plus 2?", thread_id="t1")
