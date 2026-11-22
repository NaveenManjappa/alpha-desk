"""Tests for ChatService. A fake answer stream stands in for the agent: no LLM, no network."""

from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime

import pytest

from alphadesk.domain.answer import DISCLAIMER, Answer, NoAnswerError
from alphadesk.domain.chat_events import (
    ChatEvent,
    ErrorEvent,
    FinalEvent,
    ProgressEvent,
    StatusEvent,
    TokenEvent,
)
from alphadesk.services.chat import FAILED_MESSAGE, NO_ANSWER_MESSAGE, ChatService

ANSWER = Answer(
    summary="Apple's shares are up slightly today.",
    key_figures=[],
    sources=[],
    as_of=datetime(2025, 11, 12, 16, 20, tzinfo=UTC),
    verified=True,
    disclaimer=DISCLAIMER,
)
STATUS = StatusEvent(tool="get_quote", message="Getting the latest share price")
FINAL = FinalEvent(answer=ANSWER)


class FakeAnswerStream:
    """Yields the given events, then raises `error` if one is given. Records each call."""

    def __init__(
        self, events: Sequence[ProgressEvent | FinalEvent], error: Exception | None = None
    ) -> None:
        self.events = events
        self.error = error
        self.calls: list[tuple[str, str]] = []

    async def __call__(
        self, message: str, thread_id: str
    ) -> AsyncIterator[ProgressEvent | FinalEvent]:
        self.calls.append((message, thread_id))
        for event in self.events:
            yield event
        if self.error is not None:
            raise self.error


async def _collect(service: ChatService) -> list[ChatEvent]:
    return [event async for event in service.stream_chat("Apple price?", "t1")]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_progress_then_final_are_passed_through_in_order() -> None:
    token = TokenEvent(text="Checking")
    events = await _collect(ChatService(FakeAnswerStream([STATUS, token, FINAL])))

    assert events == [STATUS, token, FINAL]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_message_and_thread_reach_the_answer_stream() -> None:
    stream = FakeAnswerStream([FINAL])

    _ = [event async for event in ChatService(stream).stream_chat("Hi", "apple")]

    assert stream.calls == [("Hi", "apple")]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_answer_ends_the_stream_with_a_helpful_error() -> None:
    stream = FakeAnswerStream([STATUS], error=NoAnswerError("refused"))

    events = await _collect(ChatService(stream))

    assert events == [STATUS, ErrorEvent(message=NO_ANSWER_MESSAGE)]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unexpected_failure_ends_with_an_error_and_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    stream = FakeAnswerStream([STATUS], error=RuntimeError("database password is hunter2"))

    events = await _collect(ChatService(stream))

    assert events == [STATUS, ErrorEvent(message=FAILED_MESSAGE)]
    # The detail goes to the log, with its traceback, never to the client.
    assert "hunter2" not in events[-1].model_dump_json()
    assert any(record.exc_info for record in caplog.records)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stream_that_ends_without_a_final_event_ends_with_an_error() -> None:
    events = await _collect(ChatService(FakeAnswerStream([STATUS])))

    assert events == [STATUS, ErrorEvent(message=FAILED_MESSAGE)]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nothing_is_sent_after_the_final_event() -> None:
    late = StatusEvent(tool="get_quote", message="too late")

    events = await _collect(ChatService(FakeAnswerStream([FINAL, late])))

    assert events == [FINAL]
