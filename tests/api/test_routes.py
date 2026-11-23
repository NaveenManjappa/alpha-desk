"""Tests for the HTTP routes, through FastAPI's test client.

The routes are handed fake services through `dependency_overrides`, so these test the
HTTP layer only: request validation, the Server-Sent Events format and status codes. No
LLM, no database.

The test client is never used as `with TestClient(app)`: that would run the app's real
startup, which reads settings and connects to Postgres.
"""

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from alphadesk.api.app import create_app
from alphadesk.api.dependencies import AppServices, get_services
from alphadesk.domain.answer import DISCLAIMER, Answer
from alphadesk.domain.chat_events import FinalEvent, ProgressEvent, StatusEvent
from alphadesk.domain.thread import AnswerMessage, QuestionMessage, Thread
from alphadesk.domain.usage import RunUsage
from alphadesk.services.chat import ChatService
from alphadesk.services.health import PostgresCheck

ANSWER = Answer(
    summary="Apple's shares are up slightly today.",
    key_figures=[],
    sources=[],
    as_of=datetime(2025, 11, 12, 16, 20, tzinfo=UTC),
    verified=True,
    disclaimer=DISCLAIMER,
)
USAGE = RunUsage(
    duration_seconds=4.2,
    input_tokens=3_000,
    output_tokens=180,
    total_tokens=3_180,
    estimated_cost_usd=0.00111,
)


class RecordingAnswerStream:
    """A status, then the answer. Records every (message, thread_id) it is asked."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def __call__(
        self, message: str, thread_id: str
    ) -> AsyncIterator[ProgressEvent | FinalEvent]:
        self.calls.append((message, thread_id))
        yield StatusEvent(tool="get_quote", message="Getting the latest share price")
        yield FinalEvent(answer=ANSWER, usage=USAGE)


async def _read_thread(thread_id: str) -> Thread:
    """A thread with one question and its answer, whatever the ID."""
    messages = [QuestionMessage(text="Apple price?"), AnswerMessage(answer=ANSWER, usage=USAGE)]
    return Thread(thread_id=thread_id, messages=messages)


def _client(
    stream: RecordingAnswerStream | None = None, check_postgres: PostgresCheck | None = None
) -> TestClient:
    """A test client whose routes get fake services instead of the real ones."""
    services = AppServices(
        chat=ChatService(stream or RecordingAnswerStream()),
        read_thread=_read_thread,
        check_postgres=check_postgres,
    )
    app = create_app()
    app.dependency_overrides[get_services] = lambda: services
    return TestClient(app)


@pytest.fixture
def client() -> TestClient:
    return _client()


def _events(body: str) -> list[tuple[str, dict[str, object]]]:
    """Parse a Server-Sent Events body into (event name, JSON data) pairs."""
    events = []
    for block in body.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in fields:
            events.append((fields["event"], json.loads(fields["data"])))
    return events


@pytest.mark.unit
def test_chat_streams_status_then_final_as_server_sent_events(client: TestClient) -> None:
    response = client.post("/chat", json={"message": "Apple price?", "thread_id": "t1"})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _events(response.text)
    assert [name for name, _ in events] == ["status", "final"]
    assert events[0][1]["tool"] == "get_quote"
    final = events[1][1]
    assert final["type"] == "final"
    assert Answer.model_validate(final["answer"]) == ANSWER
    # Usage sits beside the answer, not inside it: it describes the run, not the research.
    assert RunUsage.model_validate(final["usage"]) == USAGE
    assert "usage" not in Answer.model_fields


@pytest.mark.unit
def test_chat_passes_the_thread_id_through() -> None:
    stream = RecordingAnswerStream()
    client = _client(stream)

    client.post("/chat", json={"message": "How is Apple?", "thread_id": "apple"})
    client.post("/chat", json={"message": "  And its revenue?  ", "thread_id": "apple"})

    assert stream.calls == [("How is Apple?", "apple"), ("And its revenue?", "apple")]


@pytest.mark.unit
@pytest.mark.parametrize(
    "body",
    [
        {"thread_id": "t1"},
        {"message": "   ", "thread_id": "t1"},
        {"message": "Hi"},
        {"message": "Hi", "thread_id": "has spaces"},
        {"message": "Hi", "thread_id": "x" * 65},
        {"message": "x" * 4001, "thread_id": "t1"},
    ],
)
def test_chat_rejects_a_bad_request_before_running_anything(body: dict[str, str]) -> None:
    stream = RecordingAnswerStream()
    response = _client(stream).post("/chat", json=body)

    assert response.status_code == 422
    assert stream.calls == []


@pytest.mark.unit
def test_thread_returns_its_messages_each_with_its_type(client: TestClient) -> None:
    response = client.get("/threads/apple")

    assert response.status_code == 200
    body = response.json()
    assert body["thread_id"] == "apple"
    assert [message["type"] for message in body["messages"]] == ["question", "answer"]
    assert Thread.model_validate(body).messages[1] == AnswerMessage(answer=ANSWER, usage=USAGE)


@pytest.mark.unit
@pytest.mark.parametrize("thread_id", ["has spaces", "x" * 65])
def test_thread_rejects_a_bad_id(client: TestClient, thread_id: str) -> None:
    assert client.get(f"/threads/{thread_id}").status_code == 422


async def _up() -> bool:
    return True


async def _down() -> bool:
    return False


@pytest.mark.unit
def test_health_is_200_when_postgres_answers() -> None:
    response = _client(check_postgres=_up).get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "postgres": "ok"}


@pytest.mark.unit
def test_health_is_503_when_postgres_is_down() -> None:
    response = _client(check_postgres=_down).get("/health")

    assert response.status_code == 503
    assert response.json() == {"status": "degraded", "postgres": "unreachable"}


@pytest.mark.unit
def test_health_is_200_without_postgres_configured(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["postgres"] == "not_configured"
