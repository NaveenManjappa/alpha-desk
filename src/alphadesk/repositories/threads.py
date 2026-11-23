"""The list of conversations: which threads exist, and when each was last used.

An index beside the data. The checkpointer holds what was said in a thread, filed by
thread ID, but it is not built to say which threads there are.

There are two implementations, picked by the same setting as the checkpointer, so the list
and the conversations are always kept in the same kind of place: the one here, in memory,
and `PostgresThreadRepository`. The Postgres one is in its own module, so that a service
importing the Protocol from here does not import a database driver.
"""

from datetime import datetime
from typing import Protocol

from alphadesk.domain.thread import ThreadSummary


class ThreadRepository(Protocol):
    """What the app needs from the list of threads.

    Every method raises `StorageError` if the list cannot be reached.
    """

    async def record(self, thread_id: str, title: str, used_at: datetime) -> None:
        """Add a thread, or move its time if it is already listed. The first title stays."""
        ...

    async def list_recent(self, limit: int) -> list[ThreadSummary]:
        """The most recently used threads, newest first, at most `limit` of them."""
        ...

    async def delete(self, thread_id: str) -> None:
        """Take a thread off the list. Does nothing if it is not on it."""
        ...


class InMemoryThreadRepository:
    """Keeps the list in this process. For the tests, and for the "memory" checkpointer."""

    def __init__(self) -> None:
        self._threads: dict[str, ThreadSummary] = {}

    async def record(self, thread_id: str, title: str, used_at: datetime) -> None:
        """Add a thread, or move its time. See `ThreadRepository`."""
        known = self._threads.get(thread_id)
        self._threads[thread_id] = ThreadSummary(
            thread_id=thread_id,
            title=known.title if known else title,
            last_used_at=used_at,
        )

    async def list_recent(self, limit: int) -> list[ThreadSummary]:
        """The newest threads. See `ThreadRepository`."""
        newest_first = sorted(
            self._threads.values(), key=lambda thread: thread.last_used_at, reverse=True
        )
        return newest_first[:limit]

    async def delete(self, thread_id: str) -> None:
        """Take a thread off the list. See `ThreadRepository`."""
        self._threads.pop(thread_id, None)
