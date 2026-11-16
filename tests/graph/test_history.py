"""Tests for trimming the history sent to the model. Plain message lists: no model, no agent."""

import logging

import pytest
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage

from alphadesk.graph.history import count_history_tokens, trim_history


def _turn(number: int, result_size: int = 200) -> list[AnyMessage]:
    """One research turn: question, tool call, tool result, answer call, its confirmation."""
    return [
        HumanMessage(f"Question {number}"),
        AIMessage(
            "",
            tool_calls=[{"name": "get_quote", "args": {"ticker": "AAPL"}, "id": f"q{number}"}],
        ),
        ToolMessage("x" * result_size, tool_call_id=f"q{number}"),
        AIMessage("", tool_calls=[{"name": "AnswerDraft", "args": {}, "id": f"a{number}"}]),
        ToolMessage("Returning structured response", tool_call_id=f"a{number}"),
    ]


def _chat(turns: int) -> list[AnyMessage]:
    return [message for number in range(turns) for message in _turn(number)]


@pytest.mark.unit
def test_history_under_the_budget_is_sent_whole() -> None:
    chat = _chat(3)

    assert trim_history(chat, max_tokens=count_history_tokens(chat)) == chat


@pytest.mark.unit
def test_long_history_is_cut_to_the_newest_whole_turns_within_budget() -> None:
    chat = _chat(30)
    budget = count_history_tokens(_turn(0)) * 3  # room for exactly three turns

    kept = trim_history(chat, max_tokens=budget)

    assert count_history_tokens(kept) <= budget
    assert kept == chat[-15:]


@pytest.mark.unit
def test_trim_never_separates_a_tool_result_from_its_call() -> None:
    chat = _chat(10)
    # Budget that falls in the middle of a turn: the partial turn must go entirely.
    budget = int(count_history_tokens(_turn(0)) * 2.5)

    kept = trim_history(chat, max_tokens=budget)

    assert isinstance(kept[0], HumanMessage)
    call_ids = {call["id"] for m in kept if isinstance(m, AIMessage) for call in m.tool_calls}
    result_ids = {m.tool_call_id for m in kept if isinstance(m, ToolMessage)}
    assert result_ids == call_ids


@pytest.mark.unit
def test_a_current_turn_over_budget_is_still_sent_whole(
    caplog: pytest.LogCaptureFixture,
) -> None:
    chat = [*_chat(2), *_turn(2, result_size=10_000)]

    with caplog.at_level(logging.WARNING):
        kept = trim_history(chat, max_tokens=100)

    # Without its question the model could not answer, so the turn goes over budget.
    assert kept == chat[-5:]
    assert "over the history budget" in caplog.text


@pytest.mark.unit
def test_trimming_leaves_the_input_list_unchanged() -> None:
    chat = _chat(10)
    before = list(chat)

    trim_history(chat, max_tokens=50)

    assert chat == before
