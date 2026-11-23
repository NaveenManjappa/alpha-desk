"""The HTTP routes. Each one parses the request, calls a service and returns its output.

No business logic lives here. What a chat turn does is in `ChatService` and the agent;
what counts as healthy is in `services/health.py`. The routes only translate between HTTP
and those calls.
"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, Depends, Response, status
from fastapi.sse import EventSourceResponse, ServerSentEvent
from pydantic import BaseModel, StringConstraints

from alphadesk.api.dependencies import AppServices, get_services
from alphadesk.domain.health import HealthReport
from alphadesk.domain.thread import Thread
from alphadesk.services.health import check_health

router = APIRouter()

# `Annotated[..., Depends(...)]` tells FastAPI to call `get_services` for each request and
# pass the result in.
Services = Annotated[AppServices, Depends(get_services)]


# Letters, digits, "-" and "_" only, so an ID is safe to log and to store.
ThreadId = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_-]{1,64}$")]


class ChatRequest(BaseModel):
    """The body of `POST /chat`. The TypeScript model in `web/` mirrors it; change both together.

    Attributes:
        message: The user's question. Surrounding whitespace is removed.
        thread_id: Names the conversation. Send the same ID again to continue it.
    """

    message: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]
    thread_id: ThreadId


@router.post("/chat", response_class=EventSourceResponse)
async def chat(request: ChatRequest, services: Services) -> AsyncIterator[ServerSentEvent]:
    """Answer a message on a thread, streaming progress as Server-Sent Events.

    Each event's name is its `type` (status, token, final or error) and its data is the
    event as JSON. The stream always ends with one `final` or one `error` event.
    """
    async for event in services.chat.stream_chat(request.message, request.thread_id):
        yield ServerSentEvent(event=event.type, data=event)


@router.get("/threads/{thread_id}")
async def thread(thread_id: ThreadId, services: Services) -> Thread:
    """Return a conversation's questions and answers. A thread nobody has used is empty."""
    return await services.read_thread(thread_id)


@router.get("/health")
async def health(response: Response, services: Services) -> HealthReport:
    """Report whether the API and Postgres are up. 503 if a configured dependency is down."""
    report = await check_health(services.check_postgres)
    if report.status != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return report
