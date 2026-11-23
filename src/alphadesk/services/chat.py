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
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime

from alphadesk.domain.answer import NoAnswerError
from alphadesk.domain.chat_events import ChatEvent, ErrorEvent, FinalEvent, ProgressEvent
from alphadesk.domain.errors import RunLimitError
from alphadesk.domain.usage import RunUsage
from alphadesk.repositories.threads import ThreadRepository

logger = logging.getLogger(__name__)

# Streams the answer to (message, thread_id): progress events, then one `FinalEvent`.
# In the app this is `stream_research_agent` with the agent already filled in.
AnswerStream = Callable[[str, str], AsyncIterator[ProgressEvent | FinalEvent]]

# A conversation is listed under its first question, cut to this many characters.
TITLE_MAX_LENGTH = 80

NO_ANSWER_MESSAGE = (
    "The research desk could not produce an answer to that. "
    "Try asking about a US-listed company's price, financials or filings."
)
RUN_LIMIT_MESSAGE = (
    "That question needed more research steps than one answer is allowed. "
    "Try asking about one company and one topic at a time."
)
FAILED_MESSAGE = "Something went wrong while researching that. Please try again."


class ChatService:
    """Runs one chat turn and turns its outcome into a well-formed stream of events."""

    def __init__(self, stream_answer: AnswerStream, threads: ThreadRepository) -> None:
        """Args:
        stream_answer: Produces the answer's events for a message on a thread.
        threads: The list of conversations. Each turn puts its thread on it.
        """
        self._stream_answer = stream_answer
        self._threads = threads

    async def stream_chat(self, message: str, thread_id: str) -> AsyncIterator[ChatEvent]:
        """Answer `message` on `thread_id`, yielding events as the work happens.

        Args:
            message: The user's message, already validated by the API.
            thread_id: Names the conversation. The same ID continues it.

        Yields:
            Any `status` and `token` events, then exactly one `final` or `error` event.
            Nothing is yielded after that last event.
        """
        # The thread ID only: the message may hold personal details, so it is not logged.
        logger.info("Chat turn started on thread %s.", thread_id)
        # Before the agent runs, so a conversation whose first answer fails is listed too.
        await self._list_thread(message, thread_id)
        try:
            async for event in self._stream_answer(message, thread_id):
                yield event
                if isinstance(event, FinalEvent):
                    _log_usage(thread_id, event.usage)
                    return
        except NoAnswerError:
            logger.warning("Chat turn on thread %s ended without an answer.", thread_id)
            yield ErrorEvent(message=NO_ANSWER_MESSAGE)
            return
        except RunLimitError as exc:
            logger.warning("Chat turn on thread %s stopped: %s", thread_id, exc)
            yield ErrorEvent(message=RUN_LIMIT_MESSAGE)
            return
        except Exception:
            # Deliberately broad. This is the last place a failure can still reach the client,
            # and an unknown error must end the stream with an `error` event, not cut it off.
            # Nothing is swallowed: the full traceback goes to the log. This includes the
            # model provider failing after its own retries; a fallback model comes later.
            logger.exception("Chat turn on thread %s failed.", thread_id)
            yield ErrorEvent(message=FAILED_MESSAGE)
            return
        # The answer stream ended without a final event. That is a bug, not a user error.
        logger.error("Chat turn on thread %s ended without a final event.", thread_id)
        yield ErrorEvent(message=FAILED_MESSAGE)

    async def _list_thread(self, message: str, thread_id: str) -> None:
        """Put the thread on the list of conversations. Never raises."""
        try:
            await self._threads.record(thread_id, message[:TITLE_MAX_LENGTH], datetime.now(UTC))
        except Exception as error:
            # Deliberately broad: the list is a convenience, and no failure of it may stop a
            # chat. The type only, with no traceback, because the error can quote the title.
            logger.warning(
                "Thread %s could not be put on the list: %s.", thread_id, type(error).__name__
            )


def _log_usage(thread_id: str, usage: RunUsage) -> None:
    """One line per finished run, so cost can be watched from the logs alone."""
    logger.info(
        "Chat turn finished on thread %s: %.1fs, %d input + %d output tokens, est. $%.4f.",
        thread_id,
        usage.duration_seconds,
        usage.input_tokens,
        usage.output_tokens,
        usage.estimated_cost_usd,
    )
