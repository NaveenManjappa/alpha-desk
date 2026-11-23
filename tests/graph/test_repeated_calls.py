"""Tests for spotting repeated tool calls. Plain message lists: no model, no agent.

What the agent does about a repeat is tested in `tests/agents/test_research_agent.py`.
"""

from datetime import UTC, datetime
from typing import Any

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from alphadesk.domain.tool_results import ToolError, ToolErrorType
from alphadesk.graph.repeated_calls import repeat_rounds, repeated_call_ids


def _calls(*calls: tuple[str, str, dict[str, Any]], result: str = "result") -> list[BaseMessage]:
    """One model message asking for `(id, tool, args)` calls, and a result for each."""
    return [
        AIMessage(
            "", tool_calls=[{"id": i, "name": name, "args": args} for i, name, args in calls]
        ),
        *(ToolMessage(result, tool_call_id=i, name=name) for i, name, _ in calls),
    ]


def _filings(call_id: str, ticker: str = "NVDA") -> tuple[str, str, dict[str, Any]]:
    return (call_id, "list_recent_filings", {"ticker": ticker})


def _error(error_type: ToolErrorType) -> str:
    error = ToolError(error_type=error_type, message="It failed.", as_of=datetime.now(UTC))
    return error.model_dump_json()


@pytest.mark.unit
def test_the_same_tool_with_the_same_arguments_is_a_repeat() -> None:
    messages = [
        HumanMessage("Latest quarter?"),
        *_calls(_filings("1")),
        *_calls(_filings("2")),
        *_calls(_filings("3")),
    ]

    assert repeated_call_ids(messages) == {"2", "3"}
    assert repeat_rounds(messages) == 2


@pytest.mark.unit
def test_another_tool_or_other_arguments_is_not_a_repeat() -> None:
    messages = [
        HumanMessage("Compare Apple and Nvidia"),
        *_calls(_filings("1", "NVDA"), _filings("2", "AAPL")),
        *_calls(("3", "get_quote", {"ticker": "NVDA"})),
    ]

    assert repeated_call_ids(messages) == set()


@pytest.mark.unit
def test_the_order_of_arguments_does_not_matter() -> None:
    messages = [
        HumanMessage("q"),
        *_calls(("1", "get_quote", {"ticker": "NVDA", "day": "today"})),
        *_calls(("2", "get_quote", {"day": "today", "ticker": "NVDA"})),
    ]

    assert repeated_call_ids(messages) == {"2"}


@pytest.mark.unit
def test_twice_in_one_message_is_one_repeat() -> None:
    messages = [HumanMessage("q"), *_calls(_filings("1"), _filings("2"))]

    assert repeated_call_ids(messages) == {"2"}
    assert repeat_rounds(messages) == 1


@pytest.mark.unit
def test_every_new_message_to_the_model_starts_afresh() -> None:
    # Data from an earlier question may be out of date, so it must be fetched again.
    messages = [HumanMessage("First"), *_calls(_filings("1")), HumanMessage("Second")]

    assert repeated_call_ids([*messages, *_calls(_filings("2"))]) == set()


@pytest.mark.unit
def test_answering_twice_is_not_a_repeat() -> None:
    # The same draft sent again after a schema error is the model's business, not a fetch.
    answer = ("AnswerDraft", {"summary": ""})
    messages = [HumanMessage("q"), *_calls(("1", *answer)), *_calls(("2", *answer))]

    assert repeated_call_ids(messages) == set()


@pytest.mark.unit
def test_a_call_the_provider_failed_may_be_made_once_more() -> None:
    messages = [
        HumanMessage("q"),
        *_calls(_filings("1"), result=_error("upstream_error")),
        *_calls(_filings("2")),
    ]

    assert repeated_call_ids(messages) == set()
    assert repeat_rounds(messages) == 0


@pytest.mark.unit
@pytest.mark.parametrize("retry_result", ["result", _error("upstream_error")])
def test_a_second_retry_is_a_repeat_whether_or_not_the_first_worked(retry_result: str) -> None:
    messages = [
        HumanMessage("q"),
        *_calls(_filings("1"), result=_error("upstream_error")),
        *_calls(_filings("2"), result=retry_result),
        *_calls(_filings("3")),
    ]

    assert repeated_call_ids(messages) == {"3"}


@pytest.mark.unit
@pytest.mark.parametrize("error_type", ["invalid_input", "not_found", "unavailable"])
def test_a_failure_that_would_only_happen_again_is_not_retried(error_type: ToolErrorType) -> None:
    messages = [
        HumanMessage("q"),
        *_calls(_filings("1"), result=_error(error_type)),
        *_calls(_filings("2")),
    ]

    assert repeated_call_ids(messages) == {"2"}


@pytest.mark.unit
def test_a_repeat_in_the_same_message_is_not_a_retry_even_once_the_first_has_failed() -> None:
    # It was asked for before the failure was known. It stays a repeat, and since it never
    # ran, it does not use up the retry either.
    messages = [
        HumanMessage("q"),
        *_calls(_filings("1"), _filings("2"), result=_error("upstream_error")),
        *_calls(_filings("3")),
    ]

    assert repeated_call_ids(messages) == {"2"}
