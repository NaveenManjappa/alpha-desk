"""Tests for the research agent loop. No real LLM and no network: a scripted fake model
plays the LLM, the real tools, services and clients sit on in-memory httpx transports, and
the checkpointer keeps its state in memory."""

import asyncio
import contextlib
import json
import re
from collections.abc import Iterator, Sequence
from datetime import datetime
from typing import Any

import httpx
import pytest
from langchain_core.language_models import GenericFakeChatModel
from langchain_core.messages import (
    AIMessage,
    AIMessageChunk,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.messages.tool import tool_call_chunk
from langchain_core.outputs import ChatGenerationChunk
from langgraph.checkpoint.base import BaseCheckpointSaver
from pydantic import Field

from alphadesk.agents.research_agent import (
    ResearchRun,
    answer_from_agent_state,
    ask_research_agent,
    create_research_agent,
    load_system_prompt,
    stream_research_agent,
)
from alphadesk.domain.answer import DISCLAIMER, Answer, AnswerDraft, NoAnswerError
from alphadesk.domain.chat_events import FinalEvent, StatusEvent, TokenEvent
from alphadesk.domain.errors import RunLimitError
from alphadesk.domain.thread import AnswerMessage, QuestionMessage
from alphadesk.domain.usage import ModelPrice, RunUsage
from alphadesk.graph.checkpointer import create_checkpointer
from alphadesk.graph.history import count_history_tokens
from alphadesk.graph.threads import read_thread
from alphadesk.integrations.finnhub import FinnhubClient
from alphadesk.integrations.retry import RetryPolicy
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
    tool_names_per_call: list[list[str]] = Field(default_factory=list)

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "ScriptedChatModel":
        self.tool_names = [tool.name for tool in tools]
        return self

    def _generate(self, messages: list[BaseMessage], *args: Any, **kwargs: Any) -> Any:
        self.calls.append(list(messages))
        self.tool_names_per_call.append(self.tool_names)
        return super()._generate(messages, *args, **kwargs)

    def _stream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> Iterator[ChatGenerationChunk]:
        """Stream the next reply: its text word by word, then its tool calls.

        The agent runs with `astream`, which makes LangChain stream the model. The parent
        class's `_stream` drops tool calls, so this one sends them as one final chunk, the
        way a provider sends tool-call fragments.
        """
        reply = self._generate(messages, stop=stop, **kwargs).generations[0].message
        assert isinstance(reply, AIMessage)
        for word in re.split(r"(\s)", reply.text):
            if word:
                yield ChatGenerationChunk(message=AIMessageChunk(content=word, id=reply.id))
        tool_call_chunks = [
            tool_call_chunk(
                name=call["name"], args=json.dumps(call["args"]), id=call["id"], index=index
            )
            for index, call in enumerate(reply.tool_calls)
        ]
        # Providers report token usage once, on the last chunk.
        yield ChatGenerationChunk(
            message=AIMessageChunk(
                content="",
                id=reply.id,
                tool_call_chunks=tool_call_chunks,
                usage_metadata=reply.usage_metadata,
            )
        )


def _model(*replies: AIMessage) -> ScriptedChatModel:
    script: Iterator[AIMessage] = iter(replies)
    return ScriptedChatModel(messages=script)


def _quote_service() -> QuoteService:
    apple = httpx.Response(200, json={"c": 227.5, "d": 1.25, "dp": 0.55, "t": 1_762_966_800})
    http = httpx.AsyncClient(
        base_url="https://finnhub.io/api/v1",
        transport=httpx.MockTransport(lambda _: apple),
    )
    return QuoteService(FinnhubClient(http, NO_RETRIES))


# Large enough that no test trims unless it sets its own, smaller budget.
NO_TRIMMING = 1_000_000
# Enough model calls for every scripted conversation here, unless a test sets its own.
MAX_MODEL_CALLS = 10
NO_RETRIES = RetryPolicy(max_attempts=1)
# USD per million tokens. Round numbers, so expected costs are easy to work out by hand.
PRICE = ModelPrice(input_usd_per_million=1.0, output_usd_per_million=10.0)


def _agent(
    model: ScriptedChatModel,
    checkpointer: BaseCheckpointSaver | None = None,
    history_max_tokens: int = NO_TRIMMING,
    max_model_calls: int = MAX_MODEL_CALLS,
    quote_service: QuoteService | None = None,
) -> Any:
    """The agent with all three tools. EDGAR is never reached in these tests: it answers 503."""
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(503)))
    edgar = EdgarClient(http, RateLimiter(max_per_second=1000), NO_RETRIES)
    return create_research_agent(
        model,
        quote_service=quote_service or _quote_service(),
        financial_facts_service=FinancialFactsService(edgar),
        filings_service=FilingsService(edgar),
        history_max_tokens=history_max_tokens,
        max_model_calls=max_model_calls,
        checkpointer=checkpointer,
    )


def _chat_agent(
    model: ScriptedChatModel,
    history_max_tokens: int = NO_TRIMMING,
    max_model_calls: int = MAX_MODEL_CALLS,
) -> Any:
    """The agent with a checkpointer, as `ask_research_agent` needs it."""
    return _agent(model, create_checkpointer(), history_max_tokens, max_model_calls)


async def _run(agent: Any, question: str, thread_id: str) -> ResearchRun:
    """`ask_research_agent` with the test price filled in."""
    return await ask_research_agent(agent, question, thread_id, price=PRICE)


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

    run = await _run(_chat_agent(model), "What is Apple's share price?", "t1")

    assert run.answer.verified is True
    assert [figure.value for figure in run.answer.key_figures] == [227.5]
    assert len(model.calls) == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_failed_figure_is_sent_back_once_and_the_fixed_answer_is_verified() -> None:
    model = _model(ASK_FOR_QUOTE, ANSWER_WITH_INVENTED_CHANGE, APPLE_ANSWER)

    run = await _run(_chat_agent(model), "What is Apple's share price?", "t1")

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

    run = await _run(_chat_agent(model), "What is Apple's share price?", "t1")

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

    await _run(agent, "How is Apple doing?", thread_id="apple")
    await _run(agent, "And its price again?", thread_id="apple")

    # The model's first call of turn two (call index 2) includes turn one's question.
    second_turn = _texts(model.calls[2])
    assert "How is Apple doing?" in second_turn
    assert second_turn[-1] == "And its price again?"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_new_thread_starts_with_no_memory() -> None:
    model = _model(_quote_call("q1"), _apple_answer("a1"), FOUR)
    agent = _chat_agent(model)

    await _run(agent, "How is Apple doing?", thread_id="apple")
    await _run(agent, "What is 2 plus 2?", thread_id="other")

    other_thread = _texts(model.calls[2])
    assert "How is Apple doing?" not in other_thread
    assert other_thread[-1] == "What is 2 plus 2?"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_saved_state_for_a_thread_can_be_read_back() -> None:
    agent = _chat_agent(_model(_quote_call("q1"), _apple_answer("a1")))

    await _run(agent, "How is Apple doing?", thread_id="apple")
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

    await _run(agent, "How is Apple doing?", thread_id="apple")
    run = await _run(agent, "And its price again?", thread_id="apple")

    assert run.messages[0].text == "And its price again?"
    assert len(run.messages) == 5


@pytest.mark.unit
@pytest.mark.asyncio
async def test_data_from_an_earlier_turn_does_not_ground_a_new_answer() -> None:
    # Turn two copies the price from turn one without fetching it again, twice.
    model = _model(_quote_call("q1"), _apple_answer("a1"), _apple_answer("a2"), _apple_answer("a3"))
    agent = _chat_agent(model)

    await _run(agent, "How is Apple doing?", thread_id="apple")
    run = await _run(agent, "And its price again?", thread_id="apple")

    assert run.answer.verified is False
    assert run.answer.key_figures == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_turn_without_an_answer_never_returns_the_previous_answer() -> None:
    model = _model(_quote_call("q1"), _apple_answer("a1"), AIMessage("I can't help with that."))
    agent = _chat_agent(model)

    await _run(agent, "How is Apple doing?", thread_id="apple")

    with pytest.raises(NoAnswerError):
        await _run(agent, "Tell me a secret.", thread_id="apple")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_asking_an_agent_without_a_checkpointer_is_refused() -> None:
    with pytest.raises(ValueError, match="checkpointer"):
        await _run(_agent(_model(FOUR)), "What is 2 plus 2?", thread_id="t1")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_long_chat_sends_the_model_no_more_than_the_history_budget() -> None:
    turns = 20
    budget = 600  # roughly two turns of a price question
    replies: list[AIMessage] = []
    for turn in range(turns):
        replies += [_quote_call(f"q{turn}"), _apple_answer(f"a{turn}")]
    model = _model(*replies)
    agent = _chat_agent(model, history_max_tokens=budget)

    for turn in range(turns):
        await _run(agent, f"Question {turn}: how is Apple?", thread_id="long")

    for sent in model.calls:
        system, history = sent[0], sent[1:]
        assert isinstance(system, SystemMessage)  # the system prompt is always sent
        assert count_history_tokens(history) <= budget
        assert isinstance(history[0], HumanMessage)  # cut only before a question
    # The latest question is always there, and the oldest is long gone from the model.
    assert model.calls[-1][-3].text == f"Question {turns - 1}: how is Apple?"
    assert "Question 0: how is Apple?" not in _texts(model.calls[-1])
    # Trimming is per call only: the checkpoint still holds the whole thread.
    snapshot = await agent.aget_state({"configurable": {"thread_id": "long"}})
    assert len(snapshot.values["messages"]) == turns * 5


# --- Streaming (Slice 11) ---------------------------------------------------------------


async def _stream(agent: Any, question: str, thread_id: str = "t1") -> list[Any]:
    return [event async for event in stream_research_agent(agent, question, thread_id, price=PRICE)]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stream_sends_a_status_when_a_tool_starts_then_the_final_answer() -> None:
    events = await _stream(_chat_agent(_model(ASK_FOR_QUOTE, APPLE_ANSWER)), "Apple price?")

    assert events[0] == StatusEvent(tool="get_quote", message="Getting the latest share price")
    assert isinstance(events[-1], FinalEvent)
    assert events[-1].answer.verified is True
    assert len(events) == 2  # the answer tool gets no status of its own


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stream_sends_the_model_text_as_tokens_as_it_arrives() -> None:
    thinking = ASK_FOR_QUOTE.model_copy(update={"content": "Let me check."})

    events = await _stream(_chat_agent(_model(thinking, APPLE_ANSWER)), "Apple price?")

    tokens = [event.text for event in events if isinstance(event, TokenEvent)]
    assert "".join(tokens) == "Let me check."
    assert len(tokens) > 1  # in pieces, not one block at the end
    # Tokens arrive while the model writes, so before the status for the tool it then calls.
    assert isinstance(events[0], TokenEvent)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_tool_results_are_never_streamed_as_tokens() -> None:
    events = await _stream(_chat_agent(_model(ASK_FOR_QUOTE, APPLE_ANSWER)), "Apple price?")

    assert not any(isinstance(event, TokenEvent) for event in events)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stream_covers_both_attempts_when_grounding_retries() -> None:
    model = _model(ASK_FOR_QUOTE, ANSWER_WITH_INVENTED_CHANGE, ASK_FOR_QUOTE, APPLE_ANSWER)

    events = await _stream(_chat_agent(model), "Apple price?")

    statuses = [event for event in events if isinstance(event, StatusEvent)]
    assert len(statuses) == 2  # one per attempt
    finals = [event for event in events if isinstance(event, FinalEvent)]
    assert len(finals) == 1
    assert events[-1] is finals[0]
    assert finals[0].answer.verified is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_two_streams_on_the_same_thread_continue_one_conversation() -> None:
    model = _model(ASK_FOR_QUOTE, APPLE_ANSWER, FOUR)
    agent = _chat_agent(model)

    await _stream(agent, "How is Apple doing?", thread_id="apple")
    await _stream(agent, "And what is 2 plus 2?", thread_id="apple")

    sent = [message.text for message in model.calls[-1]]
    assert "How is Apple doing?" in sent
    assert "And what is 2 plus 2?" in sent


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stream_without_an_answer_raises_after_its_progress() -> None:
    refusal = AIMessage(content="I can't help with that.")

    with pytest.raises(NoAnswerError):
        await _stream(_chat_agent(_model(refusal)), "Tell me a secret.")


# --- Limits and usage (Slice 12) --------------------------------------------------------


def _with_usage(message: AIMessage, input_tokens: int, output_tokens: int) -> AIMessage:
    """A scripted reply that reports its token usage, as a real provider does."""
    usage = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }
    return message.model_copy(update={"usage_metadata": usage})


@pytest.mark.unit
@pytest.mark.asyncio
async def test_usage_adds_up_every_model_call_of_the_turn() -> None:
    model = _model(_with_usage(ASK_FOR_QUOTE, 1_000, 50), _with_usage(APPLE_ANSWER, 2_000, 100))

    run = await _run(_chat_agent(model), "Apple price?", "t1")

    assert run.usage.input_tokens == 3_000
    assert run.usage.output_tokens == 150
    assert run.usage.total_tokens == 3_150
    # 3,000 / 1M * $1 + 150 / 1M * $10 = $0.003 + $0.0015
    assert run.usage.estimated_cost_usd == pytest.approx(0.0045)
    assert run.usage.duration_seconds > 0


@pytest.mark.unit
@pytest.mark.asyncio
async def test_usage_covers_both_attempts_when_grounding_retries() -> None:
    model = _model(
        _with_usage(ASK_FOR_QUOTE, 100, 10),
        _with_usage(ANSWER_WITH_INVENTED_CHANGE, 200, 20),
        _with_usage(APPLE_ANSWER, 300, 30),
    )

    run = await _run(_chat_agent(model), "Apple price?", "t1")

    assert (run.usage.input_tokens, run.usage.output_tokens) == (600, 60)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_usage_counts_only_this_turn_not_earlier_ones() -> None:
    model = _model(
        _with_usage(_quote_call("q1"), 1_000, 10),
        _with_usage(_apple_answer("a1"), 1_000, 10),
        _with_usage(FOUR, 500, 5),
    )
    agent = _chat_agent(model)

    await _run(agent, "How is Apple doing?", "apple")
    run = await _run(agent, "What is 2 plus 2?", "apple")

    assert (run.usage.input_tokens, run.usage.output_tokens) == (500, 5)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_final_event_carries_usage_beside_the_answer() -> None:
    model = _model(_with_usage(ASK_FOR_QUOTE, 100, 10), _with_usage(APPLE_ANSWER, 200, 20))

    events = await _stream(_chat_agent(model), "Apple price?")

    final = events[-1]
    assert isinstance(final, FinalEvent)
    assert final.usage.total_tokens == 330


@pytest.mark.unit
@pytest.mark.asyncio
async def test_usage_is_saved_with_the_answer_in_the_thread() -> None:
    model = _model(_with_usage(ASK_FOR_QUOTE, 100, 10), _with_usage(APPLE_ANSWER, 200, 20), FOUR)
    agent = _chat_agent(model)

    run = await _run(agent, "Apple price?", "apple")
    snapshot = await agent.aget_state({"configurable": {"thread_id": "apple"}})

    # The answer tool's confirmation holds it, in `artifact`: saved, but never sent to the model.
    answer_message = snapshot.values["messages"][-1]
    assert isinstance(answer_message, ToolMessage)
    assert answer_message.name == "AnswerDraft"
    assert RunUsage.model_validate(answer_message.artifact["usage"]) == run.usage
    # Saving it did not leave the thread half-run: the next question works as normal.
    assert snapshot.next == ()
    follow_up = await _run(agent, "What is 2 plus 2?", "apple")
    assert follow_up.answer.summary == "Two plus two is four."
    # The model was sent the earlier turn, but not its usage.
    assert "Apple price?" in _texts(model.calls[-1])
    assert not any("estimated_cost_usd" in str(m.content) for m in model.calls[-1])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_looping_agent_is_stopped_at_the_model_call_limit() -> None:
    # A model that never stops asking for the price.
    looping = [_quote_call(f"q{n}") for n in range(10)]
    model = _model(*looping)

    with pytest.raises(RunLimitError):
        await _run(_chat_agent(model, max_model_calls=3), "Apple price?", "loop")

    assert len(model.calls) == 3


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_thread_stopped_at_the_limit_can_still_be_used() -> None:
    model = _model(_quote_call("q1"), _quote_call("q2"), FOUR)
    agent = _chat_agent(model, max_model_calls=2)

    with pytest.raises(RunLimitError):
        await _run(agent, "Apple price?", "loop")
    run = await _run(agent, "What is 2 plus 2?", "loop")

    assert run.answer.summary == "Two plus two is four."
    # Every tool call in the saved thread has its result, so the provider would accept it.
    sent = model.calls[-1]
    call_ids = {call["id"] for m in sent if isinstance(m, AIMessage) for call in m.tool_calls}
    result_ids = {m.tool_call_id for m in sent if isinstance(m, ToolMessage)}
    assert call_ids == result_ids


@pytest.mark.unit
@pytest.mark.asyncio
async def test_the_limit_is_per_run_not_per_thread() -> None:
    # Two questions of two model calls each, with a limit of three: each run starts at zero.
    model = _model(_quote_call("q1"), _apple_answer("a1"), _quote_call("q2"), _apple_answer("a2"))
    agent = _chat_agent(model, max_model_calls=3)

    await _run(agent, "How is Apple doing?", "apple")
    run = await _run(agent, "And now?", "apple")

    assert run.answer.verified is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_model_calls_with_no_reported_usage_log_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # The scripted replies carry no usage, as a provider would with stream usage off.
    run = await _run(_chat_agent(_model(ASK_FOR_QUOTE, APPLE_ANSWER)), "Apple price?", "t1")

    assert run.usage.total_tokens == 0
    assert any("no token usage" in record.getMessage() for record in caplog.records)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reported_usage_logs_no_warning(caplog: pytest.LogCaptureFixture) -> None:
    model = _model(_with_usage(ASK_FOR_QUOTE, 100, 10), _with_usage(APPLE_ANSWER, 200, 20))

    await _run(_chat_agent(model), "Apple price?", "t1")

    assert not any("no token usage" in record.getMessage() for record in caplog.records)


# --- Reading a thread back (Slice 15) ---------------------------------------------------


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_thread_reads_back_as_the_questions_and_answers_the_user_saw() -> None:
    model = _model(_with_usage(ASK_FOR_QUOTE, 100, 10), _with_usage(APPLE_ANSWER, 200, 20), FOUR)
    agent = _chat_agent(model)
    first = await _run(agent, "Apple price?", "apple")
    second = await _run(agent, "What is 2 plus 2?", "apple")

    thread = await read_thread(agent, "apple")

    assert thread.thread_id == "apple"
    assert thread.messages == [
        QuestionMessage(text="Apple price?"),
        AnswerMessage(answer=first.answer, usage=first.usage),
        QuestionMessage(text="What is 2 plus 2?"),
        AnswerMessage(answer=second.answer, usage=second.usage),
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_thread_reads_back_the_checked_answer_not_the_models_draft() -> None:
    # Both attempts invent a figure. The thread holds both drafts and the feedback message;
    # the user saw one question and one unverified answer without that figure.
    second_try = ANSWER_WITH_INVENTED_CHANGE.model_copy(
        update={"tool_calls": [{**ANSWER_WITH_INVENTED_CHANGE.tool_calls[0], "id": "answer-2"}]}
    )
    agent = _chat_agent(_model(ASK_FOR_QUOTE, ANSWER_WITH_INVENTED_CHANGE, second_try))
    run = await _run(agent, "Apple price?", "t1")

    thread = await read_thread(agent, "t1")

    assert thread.messages == [
        QuestionMessage(text="Apple price?"),
        AnswerMessage(answer=run.answer, usage=run.usage),
    ]
    assert run.answer.verified is False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_thread_nobody_has_used_reads_back_empty() -> None:
    assert (await read_thread(_chat_agent(_model()), "new")).messages == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_run_cut_off_during_a_tool_does_not_break_the_thread() -> None:
    # The browser is closed, or the API is stopped, while a tool call is in flight.
    tool_started = asyncio.Event()

    async def never_answers(request: httpx.Request) -> httpx.Response:
        tool_started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    http = httpx.AsyncClient(
        base_url="https://finnhub.io/api/v1", transport=httpx.MockTransport(never_answers)
    )
    model = _model(ASK_FOR_QUOTE, FOUR)
    agent = _agent(
        model,
        create_checkpointer(),
        quote_service=QuoteService(FinnhubClient(http, NO_RETRIES)),
    )
    cut_off = asyncio.create_task(_run(agent, "Apple price?", "t1"))
    await tool_started.wait()
    cut_off.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await cut_off

    run = await _run(agent, "What is 2 plus 2?", "t1")

    assert run.answer.summary == "Two plus two is four."
    # A provider rejects a tool call with no result, so none may be sent.
    assert not any(m.tool_calls for m in model.calls[-1] if isinstance(m, AIMessage))
    assert [m.type for m in (await read_thread(agent, "t1")).messages] == [
        "question",
        "question",
        "answer",
    ]


# --- Repeated tool calls ----------------------------------------------------------------


class CountingQuotes:
    """A fake Finnhub that counts how often it is asked, and may fail the first few times."""

    def __init__(self, failures: int = 0) -> None:
        self.requests = 0
        self._failures = failures

    def service(self) -> QuoteService:
        http = httpx.AsyncClient(
            base_url="https://finnhub.io/api/v1", transport=httpx.MockTransport(self._answer)
        )
        return QuoteService(FinnhubClient(http, NO_RETRIES))

    def _answer(self, request: httpx.Request) -> httpx.Response:
        self.requests += 1
        if self.requests <= self._failures:
            raise httpx.ReadTimeout("too slow", request=request)
        return httpx.Response(200, json={"c": 227.5, "d": 1.25, "dp": 0.55, "t": 1_762_966_800})


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_repeated_tool_call_is_not_run_and_the_model_is_told_to_answer() -> None:
    quotes = CountingQuotes()
    model = _model(_quote_call("q1"), _quote_call("q2"), _apple_answer("a1"))
    agent = _agent(model, create_checkpointer(), quote_service=quotes.service())

    run = await _run(agent, "Apple price?", "t1")

    assert quotes.requests == 1
    refusal = json.loads(model.calls[2][-1].text)
    assert refusal["error_type"] == "repeated_call"
    assert "get_quote" in refusal["message"]
    # The first result still grounds the answer. A refusal is not evidence, and not a failure.
    assert run.answer.verified is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_model_that_keeps_repeating_is_left_only_the_answer_tool() -> None:
    quotes = CountingQuotes()
    model = _model(_quote_call("q1"), _quote_call("q2"), _quote_call("q3"), _apple_answer("a1"))
    agent = _agent(model, create_checkpointer(), quote_service=quotes.service())

    run = await _run(agent, "Apple price?", "t1")

    assert run.answer.summary == "Apple's shares are up slightly today."
    assert quotes.requests == 1
    # A first repeat is only refused. After a second, the data tools are gone.
    assert "get_quote" in model.tool_names_per_call[2]
    assert model.tool_names_per_call[3] == ["AnswerDraft"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_the_next_question_may_fetch_the_same_data_again_with_every_tool() -> None:
    quotes = CountingQuotes()
    model = _model(
        *[_quote_call("q1"), _quote_call("q2"), _quote_call("q3"), _apple_answer("a1")],
        *[_quote_call("q4"), _apple_answer("a2")],
    )
    agent = _agent(model, create_checkpointer(), quote_service=quotes.service())

    await _run(agent, "Apple price?", "t1")
    run = await _run(agent, "And now?", "t1")

    assert quotes.requests == 2
    assert "get_quote" in model.tool_names_per_call[4]
    assert run.answer.verified is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_the_model_may_retry_a_tool_once_after_the_provider_failed() -> None:
    quotes = CountingQuotes(failures=1)
    model = _model(_quote_call("q1"), _quote_call("q2"), _apple_answer("a1"))
    agent = _agent(model, create_checkpointer(), quote_service=quotes.service())

    run = await _run(agent, "Apple price?", "t1")

    assert quotes.requests == 2
    assert run.answer.verified is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_provider_that_stays_down_is_asked_twice_and_no_more() -> None:
    quotes = CountingQuotes(failures=99)
    # Two answers: the first one's price has nothing to support it, so grounding asks again.
    model = _model(
        *[_quote_call(f"q{n}") for n in range(1, 5)], _apple_answer("a1"), _apple_answer("a2")
    )
    agent = _agent(model, create_checkpointer(), quote_service=quotes.service())

    await _run(agent, "Apple price?", "t1")

    assert quotes.requests == 2
    assert json.loads(model.calls[3][-1].text)["error_type"] == "repeated_call"
    assert model.tool_names_per_call[4] == ["AnswerDraft"]


@pytest.mark.unit
def test_prompt_says_there_are_no_quarterly_figures() -> None:
    assert "no tool gives quarterly figures" in load_system_prompt().lower()
