"""Unit tests for how the Postgres thread repository reports failures. No database.

What it stores and reads back is covered by test_postgres_threads_integration.py.
"""

from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import psycopg
import pytest

from alphadesk.config.settings import Settings
from alphadesk.domain.errors import StorageError
from alphadesk.repositories import postgres_threads
from alphadesk.repositories.postgres_threads import PostgresThreadRepository, setup_thread_tables

Operation = Callable[[PostgresThreadRepository], Awaitable[object]]

OPERATIONS: list[Operation] = [
    lambda repository: repository.record("apple", "my secret question", datetime.now(UTC)),
    lambda repository: repository.list_recent(50),
    lambda repository: repository.delete("apple"),
]


def _settings() -> Settings:
    return Settings(_env_file=None, openai_api_key="test-key")  # pyright: ignore[reportCallIssue, reportArgumentType]


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("operation", OPERATIONS, ids=["record", "list_recent", "delete"])
async def test_a_database_failure_becomes_a_storage_error_without_the_details(
    operation: Operation, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    @asynccontextmanager
    async def failing_connection(settings: Settings, schema: str) -> AsyncGenerator[None]:
        raise psycopg.OperationalError("row (my secret question) on host db.internal")
        yield

    monkeypatch.setattr(postgres_threads, "connect_to_postgres", failing_connection)

    with pytest.raises(StorageError) as caught:
        await operation(PostgresThreadRepository(_settings()))

    # Postgres errors can quote the row or the host. Only the kind of error is passed on.
    assert "OperationalError" in str(caught.value)
    assert "secret" not in str(caught.value) + caplog.text
    assert "db.internal" not in str(caught.value) + caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_setup_without_a_postgres_url_names_the_setting() -> None:
    with pytest.raises(ValueError, match="ALPHADESK_POSTGRES_URL"):
        await setup_thread_tables(_settings())
