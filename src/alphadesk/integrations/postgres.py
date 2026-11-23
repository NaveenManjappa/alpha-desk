"""Connections to the Postgres database (ADR 005).

One database holds several concerns, each in its own schema: `checkpoints` and
`conversations` now, and later `memory`, `portfolio` and `audit`. A connection opened here
for a schema finds that schema's tables by their plain names, because the schema is put on
its `search_path`.
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import psycopg
from psycopg import AsyncConnection, sql
from psycopg.rows import DictRow, dict_row

from alphadesk.config.settings import Settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def connect_to_postgres(
    settings: Settings, schema: str
) -> AsyncGenerator[AsyncConnection[DictRow]]:
    """Open one async connection to Postgres, working in `schema`. Closed on exit.

    The connection is set up the way LangGraph's Postgres checkpointer requires:

    - `autocommit=True`: each statement commits on its own. Without it, the tables
      created by `setup()` and every checkpoint written would sit in a transaction
      that is never committed.
    - `row_factory=dict_row`: rows come back as dicts, because the checkpointer reads
      columns by name.
    - `prepare_threshold=0`: never use server-side prepared statements, which break
      behind connection poolers such as PgBouncer (and Neon's pooled endpoint).

    Args:
        settings: Supplies `postgres_url` and `postgres_timeout_seconds`.
        schema: The schema this connection works in.

    Yields:
        The open connection.

    Raises:
        ValueError: `postgres_url` is not set.
        psycopg.OperationalError: The database cannot be reached in time.
    """
    if settings.postgres_url is None:
        raise ValueError("ALPHADESK_POSTGRES_URL is not set. See .env.example.")
    timeout = settings.postgres_timeout_seconds
    # `connect` returns `Self`, so the row type is named on the class for the type checker.
    async with await AsyncConnection[DictRow].connect(
        settings.postgres_url.get_secret_value(),
        autocommit=True,
        row_factory=dict_row,
        prepare_threshold=0,
        # Give up connecting after this many seconds, rather than hanging.
        connect_timeout=timeout,
        # Server settings for this session: which schema to use, and a cap on how long
        # any one statement may run (in milliseconds).
        options=f"-c search_path={schema} -c statement_timeout={timeout * 1000}",
    ) as connection:
        logger.debug("Connected to Postgres, schema %s.", schema)
        yield connection


async def postgres_is_reachable(settings: Settings) -> bool:
    """Open a fresh connection and run `SELECT 1`: can the database answer right now?

    A fresh connection, rather than the checkpointer's, so the check tests that new
    connections can be made, and never waits behind a running chat turn.

    Args:
        settings: Supplies `postgres_url` and the timeout, which bounds the check.

    Returns:
        True if the query ran. False if the database could not be reached or failed; the
        reason is logged.

    Raises:
        ValueError: `postgres_url` is not set. Check it is set before calling.
    """
    try:
        async with connect_to_postgres(settings, "public") as connection:
            await connection.execute("SELECT 1")
    except psycopg.Error as error:
        # The error's type only: its message can include the host and user name.
        logger.warning("Postgres health check failed: %s.", type(error).__name__)
        return False
    return True


async def create_schema(connection: AsyncConnection[DictRow], schema: str) -> None:
    """Create `schema` if it does not exist yet. Safe to run again."""
    # sql.Identifier quotes the name safely; never paste names into SQL with an f-string.
    statement = sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(schema))
    await connection.execute(statement)
