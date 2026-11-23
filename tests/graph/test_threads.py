"""Tests for turning a thread's saved messages into the conversation the user saw."""

from datetime import UTC, datetime

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from alphadesk.domain.answer import DISCLAIMER, Answer
from alphadesk.domain.thread import AnswerMessage, QuestionMessage
from alphadesk.domain.usage import RunUsage
from alphadesk.graph.threads import desk_message, thread_messages

ANSWER = AnswerMessage(
    answer=Answer(
        summary="Apple's revenue grew.",
        key_figures=[],
        sources=[],
        as_of=datetime(2026, 11, 23, 10, 0, tzinfo=UTC),
        verified=False,
        disclaimer=DISCLAIMER,
    ),
    usage=RunUsage(
        duration_seconds=4.2,
        input_tokens=3_000,
        output_tokens=180,
        total_tokens=3_180,
        estimated_cost_usd=0.0041,
    ),
)

TOOL_CALL = AIMessage("", tool_calls=[{"name": "get_quote", "args": {}, "id": "q1"}])
TOOL_RESULT = ToolMessage('{"price": 1}', tool_call_id="q1", name="get_quote")


def _answer_message(artifact: object) -> ToolMessage:
    return ToolMessage("ok", tool_call_id="a1", name="AnswerDraft", artifact=artifact)


@pytest.mark.unit
def test_only_questions_and_answers_are_kept_in_order() -> None:
    saved = [
        HumanMessage("How is Apple doing?"),
        TOOL_CALL,
        TOOL_RESULT,
        _answer_message(ANSWER.model_dump(mode="json")),
        HumanMessage("And its revenue?"),
    ]

    assert thread_messages(saved) == [
        QuestionMessage(text="How is Apple doing?"),
        ANSWER,
        QuestionMessage(text="And its revenue?"),
    ]


@pytest.mark.unit
def test_grounding_feedback_is_not_shown_as_a_question() -> None:
    saved = [HumanMessage("Apple price?"), desk_message("Some figures could not be matched")]

    assert thread_messages(saved) == [QuestionMessage(text="Apple price?")]


@pytest.mark.unit
@pytest.mark.parametrize(
    "artifact",
    [{"usage": ANSWER.usage.model_dump(mode="json")}, {"type": "from-the-future"}, "text"],
    ids=["saved before answers were kept", "unknown type", "not an object"],
)
def test_an_answer_that_cannot_be_read_is_skipped_with_a_warning(
    artifact: object, caplog: pytest.LogCaptureFixture
) -> None:
    saved = [HumanMessage("Apple price?"), _answer_message(artifact)]

    assert thread_messages(saved) == [QuestionMessage(text="Apple price?")]
    assert "could not be read" in caplog.text


@pytest.mark.unit
def test_a_thread_with_no_messages_is_empty() -> None:
    assert thread_messages([]) == []
