"""The checkpointer: where the agent's state is saved after every step.

A checkpointer gives a graph short-term memory. After each step (the user's input, every
model call, every tool call) LangGraph writes a checkpoint: a snapshot of the whole state,
filed under the run's `thread_id`. The next run on the same thread loads the latest
checkpoint first, so the model sees the earlier turns. A different `thread_id` starts from
nothing.

There are two kinds, chosen by the `checkpointer` setting:

- "memory": checkpoints live in a dict in this process and vanish when it exits. Unit
  tests use this one, so they need no database.
- "postgres": checkpoints are rows in Postgres, so a conversation survives a restart.
  The tables must exist first: run `make setup-db` once (it calls `setup_checkpointer`).

Both have the same interface, so the agent does not know or care which one it has.
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import psycopg
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from alphadesk.config.settings import Settings
from alphadesk.domain.errors import StorageError
from alphadesk.integrations.postgres import connect_to_postgres, create_schema

logger = logging.getLogger(__name__)

# The Postgres schema that holds the checkpoint tables (ADR 005: one schema per concern).
CHECKPOINT_SCHEMA = "checkpoints"

# Our own classes that may be rebuilt from a checkpoint, as (module, class name).
# A checkpoint stores the agent's `structured_response`, an `AnswerDraft`. LangGraph only
# rebuilds classes it is told are safe, because loading a checkpoint must never run code
# named in the data. Messages and other LangChain types are already on its safe list.
_ALLOWED_TYPES = [("alphadesk.domain.answer", "AnswerDraft")]


def _serializer() -> JsonPlusSerializer:
    """How state is turned into bytes and back. Both checkpointers use the same one."""
    return JsonPlusSerializer(allowed_msgpack_modules=_ALLOWED_TYPES)


def create_checkpointer() -> InMemorySaver:
    """Create an in-memory checkpointer.

    Returns:
        A fresh, empty checkpointer. Pass it to `create_research_agent`, and keep using the
        same one for a conversation: memory lives inside this object.
    """
    return InMemorySaver(serde=_serializer())


@asynccontextmanager
async def open_checkpointer(settings: Settings) -> AsyncGenerator[BaseCheckpointSaver]:
    """Open the checkpointer named by `settings.checkpointer`. Closed on exit.

    A context manager, because the Postgres one holds an open database connection that
    must be closed when the program is done with it.

    Args:
        settings: `checkpointer` picks the kind; Postgres also reads `postgres_url`.

    Yields:
        The checkpointer. Pass it to `create_research_agent`.
    """
    if settings.checkpointer == "memory":
        yield create_checkpointer()
        return
    async with connect_to_postgres(settings, CHECKPOINT_SCHEMA) as connection:
        yield AsyncPostgresSaver(connection, serde=_serializer())


async def delete_checkpoints(checkpointer: BaseCheckpointSaver, thread_id: str) -> None:
    """Delete everything saved for a thread. A thread with nothing saved is not an error.

    Args:
        checkpointer: Where the agent saves its threads.
        thread_id: Names the conversation.

    Raises:
        StorageError: The database could not be reached, or failed. Some of the thread's
            rows may be gone already; calling again removes the rest.
    """
    try:
        await checkpointer.adelete_thread(thread_id)
    except psycopg.Error as error:
        # The error's type only: its message can include the host and user name.
        name = type(error).__name__
        logger.warning("Checkpoints of thread %s could not be deleted: %s.", thread_id, name)
        raise StorageError(name) from error


async def setup_checkpointer(settings: Settings) -> None:
    """Create the checkpoint schema and tables in Postgres. Safe to run again.

    `AsyncPostgresSaver.setup()` creates the tables and runs any migrations a newer
    version of LangGraph needs; it records which ones it has run, so a second call only
    does new work. Run it as a separate step (`make setup-db`), not on every start, so
    the program never changes the database shape as a side effect of starting up.

    Args:
        settings: Supplies `postgres_url`, whatever `checkpointer` is set to.
    """
    async with connect_to_postgres(settings, CHECKPOINT_SCHEMA) as connection:
        await create_schema(connection, CHECKPOINT_SCHEMA)
        await AsyncPostgresSaver(connection, serde=_serializer()).setup()
