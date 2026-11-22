"""Chat orchestration: one user message in, a stream of chat events out.

`ChatService` sits between the API and the agent. It promises the client one thing the
agent alone does not: every stream ends with exactly one `final` or `error` event, whatever
went wrong on the way. Once a streamed response has started, its HTTP status (200) has
already been sent, so a failure can no longer become a 500. It has to be told to the
client as an event, inside the stream.

The service does not know how the answer is produced. It is given a function that streams
one (`AnswerStream`), so this module needs no LangChain import, and tests can pass a fake.
"""

import logging
import time
from collections.abc import AsyncIterator, Callable

from alphadesk.domain.answer import NoAnswerError
from alphadesk.domain.chat_events import ChatEvent, ErrorEvent, FinalEvent, ProgressEvent

logger = logging.getLogger(__name__)

# Streams the answer to (message, thread_id): progress events, then one `FinalEvent`.
# In the app this is `stream_research_agent` with the agent already filled in.
AnswerStream = Callable[[str, str], AsyncIterator[ProgressEvent | FinalEvent]]

NO_ANSWER_MESSAGE = (
    "The research desk could not produce an answer to that. "
    "Try asking about a US-listed company's price, financials or filings."
)
FAILED_MESSAGE = "Something went wrong while researching that. Please try again."


class ChatService:
    """Runs one chat turn and turns its outcome into a well-formed stream of events."""

    def __init__(self, stream_answer: AnswerStream) -> None:
        """Args:
        stream_answer: Produces the answer's events for a message on a thread.
        """
        self._stream_answer = stream_answer

    async def stream_chat(self, message: str, thread_id: str) -> AsyncIterator[ChatEvent]:
        """Answer `message` on `thread_id`, yielding events as the work happens.

        Args:
            message: The user's message, already validated by the API.
            thread_id: Names the conversation. The same ID continues it.

        Yields:
            Any `status` and `token` events, then exactly one `final` or `error` event.
            Nothing is yielded after that last event.
        """
        started = time.perf_counter()
        # The thread ID only: the message may hold personal details, so it is not logged.
        logger.info("Chat turn started on thread %s.", thread_id)
        try:
            async for event in self._stream_answer(message, thread_id):
                yield event
                if isinstance(event, FinalEvent):
                    logger.info(
                        "Chat turn finished on thread %s in %.1fs.",
                        thread_id,
                        time.perf_counter() - started,
                    )
                    return
        except NoAnswerError:
            logger.warning("Chat turn on thread %s ended without an answer.", thread_id)
            yield ErrorEvent(message=NO_ANSWER_MESSAGE)
            return
        except Exception:
            # Deliberately broad. This is the last place a failure can still reach the client,
            # and an unknown error must end the stream with an `error` event, not cut it off.
            # Nothing is swallowed: the full traceback goes to the log. Slice 12 adds
            # specific, friendlier handling for the failures we expect.
            logger.exception("Chat turn on thread %s failed.", thread_id)
            yield ErrorEvent(message=FAILED_MESSAGE)
            return
        # The answer stream ended without a final event. That is a bug, not a user error.
        logger.error("Chat turn on thread %s ended without a final event.", thread_id)
        yield ErrorEvent(message=FAILED_MESSAGE)
