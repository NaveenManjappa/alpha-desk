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
from alphadesk.domain.errors import RunLimitError, StorageError
from alphadesk.domain.usage import RunUsage
from alphadesk.repositories.threads import InMemoryThreadRepository
from alphadesk.services.chat import (
    FAILED_MESSAGE,
    NO_ANSWER_MESSAGE,
    RUN_LIMIT_MESSAGE,
    TITLE_MAX_LENGTH,
    AnswerStream,
    ChatService,
)

ANSWER = Answer(
    summary="Apple's shares are up slightly today.",
    key_figures=[],
    sources=[],
    as_of=datetime(2025, 11, 12, 16, 20, tzinfo=UTC),
    verified=True,
    disclaimer=DISCLAIMER,
)
STATUS = StatusEvent(tool="get_quote", message="Getting the latest share price")
USAGE = RunUsage(
    duration_seconds=4.2,
    input_tokens=3_000,
    output_tokens=180,
    total_tokens=3_180,
    estimated_cost_usd=0.00111,
)
FINAL = FinalEvent(answer=ANSWER, usage=USAGE)


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


class BrokenRepository(InMemoryThreadRepository):
    """Fails every write, with an error that quotes the question as Postgres can."""

    def __init__(self, error: Exception) -> None:
        super().__init__()
        self.error = error

    async def record(self, thread_id: str, title: str, used_at: datetime) -> None:
        raise self.error


def _service(stream: AnswerStream, threads: InMemoryThreadRepository | None = None) -> ChatService:
    return ChatService(stream, threads or InMemoryThreadRepository())


async def _collect(service: ChatService) -> list[ChatEvent]:
    return [event async for event in service.stream_chat("Apple price?", "t1")]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_progress_then_final_are_passed_through_in_order() -> None:
    token = TokenEvent(text="Checking")
    events = await _collect(_service(FakeAnswerStream([STATUS, token, FINAL])))

    assert events == [STATUS, token, FINAL]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_message_and_thread_reach_the_answer_stream() -> None:
    stream = FakeAnswerStream([FINAL])

    _ = [event async for event in _service(stream).stream_chat("Hi", "apple")]

    assert stream.calls == [("Hi", "apple")]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_answer_ends_the_stream_with_a_helpful_error() -> None:
    stream = FakeAnswerStream([STATUS], error=NoAnswerError("refused"))

    events = await _collect(_service(stream))

    assert events == [STATUS, ErrorEvent(message=NO_ANSWER_MESSAGE)]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unexpected_failure_ends_with_an_error_and_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    stream = FakeAnswerStream([STATUS], error=RuntimeError("database password is hunter2"))

    events = await _collect(_service(stream))

    assert events == [STATUS, ErrorEvent(message=FAILED_MESSAGE)]
    # The detail goes to the log, with its traceback, never to the client.
    assert "hunter2" not in events[-1].model_dump_json()
    assert any(record.exc_info for record in caplog.records)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_stream_that_ends_without_a_final_event_ends_with_an_error() -> None:
    events = await _collect(_service(FakeAnswerStream([STATUS])))

    assert events == [STATUS, ErrorEvent(message=FAILED_MESSAGE)]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nothing_is_sent_after_the_final_event() -> None:
    late = StatusEvent(tool="get_quote", message="too late")

    events = await _collect(_service(FakeAnswerStream([FINAL, late])))

    assert events == [FINAL]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_step_limit_ends_with_a_friendly_error() -> None:
    stream = FakeAnswerStream([STATUS], error=RunLimitError("8 model calls"))

    events = await _collect(_service(stream))

    assert events == [STATUS, ErrorEvent(message=RUN_LIMIT_MESSAGE)]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_finished_run_logs_one_line_with_tokens_and_cost(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level("INFO")

    await _collect(_service(FakeAnswerStream([STATUS, FINAL])))

    finished = [r.getMessage() for r in caplog.records if "finished" in r.getMessage()]
    assert len(finished) == 1
    assert "3000 input" in finished[0]
    assert "180 output" in finished[0]
    assert "$0.0011" in finished[0]
    assert "4.2" in finished[0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_turn_is_recorded_before_the_agent_runs() -> None:
    threads = InMemoryThreadRepository()
    listed_when_asked: list[str] = []

    async def stream(message: str, thread_id: str) -> AsyncIterator[ProgressEvent | FinalEvent]:
        listed_when_asked.extend(t.thread_id for t in await threads.list_recent(50))
        yield FINAL

    before = datetime.now(UTC)
    await _collect(_service(stream, threads))

    assert listed_when_asked == ["t1"]
    [summary] = await threads.list_recent(50)
    assert summary.title == "Apple price?"
    assert before <= summary.last_used_at <= datetime.now(UTC)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_conversation_whose_first_answer_failed_is_listed() -> None:
    threads = InMemoryThreadRepository()

    await _collect(_service(FakeAnswerStream([], error=RuntimeError("boom")), threads))

    assert [t.thread_id for t in await threads.list_recent(50)] == ["t1"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_the_title_is_the_first_question_cut_to_length() -> None:
    threads = InMemoryThreadRepository()
    service = _service(FakeAnswerStream([FINAL]), threads)

    _ = [event async for event in service.stream_chat("x" * 200, "t1")]

    [summary] = await threads.list_recent(50)
    assert TITLE_MAX_LENGTH == 80
    assert summary.title == "x" * 80


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_second_turn_keeps_the_title_and_moves_the_time() -> None:
    threads = InMemoryThreadRepository()
    service = _service(FakeAnswerStream([FINAL]), threads)
    _ = [event async for event in service.stream_chat("How is Apple?", "t1")]
    [first] = await threads.list_recent(50)

    _ = [event async for event in service.stream_chat("And its revenue?", "t1")]

    [second] = await threads.list_recent(50)
    assert second.title == "How is Apple?"
    assert second.last_used_at > first.last_used_at


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [StorageError("Apple price?"), RuntimeError("a bug, at Apple price?")],
    ids=["database down", "unexpected"],
)
async def test_a_failing_repository_does_not_stop_the_answer(
    error: Exception, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("DEBUG")

    events = await _collect(_service(FakeAnswerStream([STATUS, FINAL]), BrokenRepository(error)))

    assert events == [STATUS, FINAL]
    assert type(error).__name__ in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_question_text_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("DEBUG")
    broken = BrokenRepository(StorageError("Apple price?"))

    await _collect(_service(FakeAnswerStream([FINAL])))
    await _collect(_service(FakeAnswerStream([FINAL]), broken))

    assert "Apple price?" not in caplog.text
