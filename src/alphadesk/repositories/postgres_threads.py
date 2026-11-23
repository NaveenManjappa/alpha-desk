"""The list of conversations in Postgres, in its own `conversations` schema (ADR 005)."""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import datetime

import psycopg
from psycopg import AsyncConnection
from psycopg.rows import DictRow

from alphadesk.config.settings import Settings
from alphadesk.domain.errors import StorageError
from alphadesk.domain.thread import ThreadSummary
from alphadesk.integrations.postgres import connect_to_postgres, create_schema

logger = logging.getLogger(__name__)

CONVERSATIONS_SCHEMA = "conversations"

_CREATE_TABLE = """
    CREATE TABLE IF NOT EXISTS threads (
        thread_id    text        PRIMARY KEY,
        title        text        NOT NULL,
        created_at   timestamptz NOT NULL,
        last_used_at timestamptz NOT NULL
    )
"""

# One statement, so two requests that start the same thread at once cannot both find it
# missing and then both insert it. Postgres makes the second one take the update path.
_RECORD = """
    INSERT INTO threads (thread_id, title, created_at, last_used_at)
    VALUES (%(thread_id)s, %(title)s, %(used_at)s, %(used_at)s)
    ON CONFLICT (thread_id) DO UPDATE SET last_used_at = excluded.last_used_at
"""

_LIST_RECENT = """
    SELECT thread_id, title, last_used_at
    FROM threads
    ORDER BY last_used_at DESC
    LIMIT %(limit)s
"""

_DELETE = "DELETE FROM threads WHERE thread_id = %(thread_id)s"


class PostgresThreadRepository:
    """Keeps the list in Postgres. The table must exist first: run `make setup-db`.

    Each call opens its own short-lived connection, as the health check does. That costs a
    few milliseconds, and means the list works again as soon as a restarted Postgres does.
    """

    def __init__(self, settings: Settings) -> None:
        """Args:
        settings: Supplies `postgres_url` and the timeout.
        """
        self._settings = settings

    async def record(self, thread_id: str, title: str, used_at: datetime) -> None:
        """Add a thread, or move its time. See `ThreadRepository`."""
        values = {"thread_id": thread_id, "title": title, "used_at": used_at}
        async with self._connection() as connection:
            await connection.execute(_RECORD, values)

    async def list_recent(self, limit: int) -> list[ThreadSummary]:
        """The newest threads. See `ThreadRepository`."""
        async with self._connection() as connection:
            cursor = await connection.execute(_LIST_RECENT, {"limit": limit})
            rows = await cursor.fetchall()
        return [ThreadSummary.model_validate(row) for row in rows]

    async def delete(self, thread_id: str) -> None:
        """Take a thread off the list. See `ThreadRepository`."""
        async with self._connection() as connection:
            await connection.execute(_DELETE, {"thread_id": thread_id})

    @asynccontextmanager
    async def _connection(self) -> AsyncGenerator[AsyncConnection[DictRow]]:
        """A connection for one call, whose database errors come out as `StorageError`."""
        try:
            async with connect_to_postgres(self._settings, CONVERSATIONS_SCHEMA) as connection:
                yield connection
        except psycopg.Error as error:
            # The error's type only: its message can quote the host, or the row and so the
            # user's question. `UndefinedTable` means `make setup-db` has not been run.
            name = type(error).__name__
            logger.warning("The conversation list could not be reached: %s.", name)
            raise StorageError(name) from error


async def setup_thread_tables(settings: Settings) -> None:
    """Create the `conversations` schema and its table. Safe to run again.

    Args:
        settings: Supplies `postgres_url`, whatever `checkpointer` is set to.
    """
    async with connect_to_postgres(settings, CONVERSATIONS_SCHEMA) as connection:
        await create_schema(connection, CONVERSATIONS_SCHEMA)
        await connection.execute(_CREATE_TABLE)
