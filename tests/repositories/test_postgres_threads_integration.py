"""Integration tests for the Postgres thread repository, against a real database.

Skipped unless TEST_POSTGRES_URL is set, so `make check` never needs Docker. To run:

    docker compose up -d
    TEST_POSTGRES_URL=postgresql://alphadesk:alphadesk@localhost:5433/alphadesk \\
        uv run pytest -m integration

The database may hold real conversations, so each test uses its own random thread IDs,
looks only at those, and removes them afterwards. Their times are far in the future, which
puts them at the top of the list whatever else is there.
"""

import asyncio
import os
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import START, MessagesState, StateGraph

from alphadesk.config.settings import Settings
from alphadesk.domain.thread import ThreadSummary
from alphadesk.graph.checkpointer import (
    delete_checkpoints,
    open_checkpointer,
    setup_checkpointer,
)
from alphadesk.integrations.postgres import connect_to_postgres
from alphadesk.repositories.postgres_threads import PostgresThreadRepository, setup_thread_tables
from alphadesk.services.threads import ThreadService

# Not an ALPHADESK_ variable: the shared conftest removes those before every test.
POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not POSTGRES_URL, reason="TEST_POSTGRES_URL is not set"),
]

FUTURE = datetime(2999, 1, 1, 12, 0, tzinfo=UTC)


def _settings() -> Settings:
    overrides = {"openai_api_key": "test-key", "checkpointer": "postgres"}
    return Settings(_env_file=None, postgres_url=POSTGRES_URL, **overrides)  # pyright: ignore[reportCallIssue]


@pytest_asyncio.fixture
async def repository() -> PostgresThreadRepository:
    await setup_thread_tables(_settings())
    return PostgresThreadRepository(_settings())


@pytest_asyncio.fixture
async def ids(repository: PostgresThreadRepository) -> AsyncGenerator[list[str]]:
    """Three thread IDs nobody else uses. Their rows are removed after the test."""
    thread_ids = [f"test-{uuid4().hex}" for _ in range(3)]
    yield thread_ids
    for thread_id in thread_ids:
        await repository.delete(thread_id)


async def _listed(repository: PostgresThreadRepository, ids: list[str]) -> list[ThreadSummary]:
    """The rows this test made, in the order they are listed."""
    return [t for t in await repository.list_recent(50) if t.thread_id in ids]


@pytest.mark.asyncio
async def test_setup_can_run_twice_and_keeps_the_rows(
    repository: PostgresThreadRepository, ids: list[str]
) -> None:
    await repository.record(ids[0], "How is Apple?", FUTURE)

    await setup_thread_tables(_settings())

    assert len(await _listed(repository, ids)) == 1


@pytest.mark.asyncio
async def test_a_second_turn_keeps_the_title_and_moves_the_time(
    repository: PostgresThreadRepository, ids: list[str]
) -> None:
    later = FUTURE + timedelta(minutes=5)

    await repository.record(ids[0], "How is Apple?", FUTURE)
    await repository.record(ids[0], "And its revenue?", later)

    assert await _listed(repository, ids) == [
        ThreadSummary(thread_id=ids[0], title="How is Apple?", last_used_at=later)
    ]


@pytest.mark.asyncio
async def test_newest_first_up_to_the_limit(
    repository: PostgresThreadRepository, ids: list[str]
) -> None:
    for minute, thread_id in enumerate(ids):
        await repository.record(thread_id, "Hi", FUTURE + timedelta(minutes=minute))

    assert [t.thread_id for t in await repository.list_recent(2)] == [ids[2], ids[1]]


@pytest.mark.asyncio
async def test_two_writes_for_one_new_thread_at_the_same_time_make_one_row(
    repository: PostgresThreadRepository, ids: list[str]
) -> None:
    # Each call has its own connection, so these really do race in the database.
    await asyncio.gather(
        repository.record(ids[0], "First", FUTURE),
        repository.record(ids[0], "Second", FUTURE),
    )

    rows = await _listed(repository, ids)
    assert len(rows) == 1
    assert rows[0].title in {"First", "Second"}


@pytest.mark.asyncio
async def test_delete_leaves_other_threads_alone_and_can_be_repeated(
    repository: PostgresThreadRepository, ids: list[str]
) -> None:
    await repository.record(ids[0], "Apple?", FUTURE)
    await repository.record(ids[1], "Nvidia?", FUTURE)

    await repository.delete(ids[0])
    await repository.delete(ids[0])

    assert [t.thread_id for t in await _listed(repository, ids)] == [ids[1]]


async def _checkpoint_rows(thread_id: str) -> int:
    """How many rows the checkpoint tables hold for a thread, in all three together."""
    query = """
        SELECT (SELECT count(*) FROM checkpoints WHERE thread_id = %(id)s)
             + (SELECT count(*) FROM checkpoint_blobs WHERE thread_id = %(id)s)
             + (SELECT count(*) FROM checkpoint_writes WHERE thread_id = %(id)s) AS total
    """
    async with connect_to_postgres(_settings(), "checkpoints") as connection:
        cursor = await connection.execute(query, {"id": thread_id})
        row = await cursor.fetchone()
    assert row is not None
    return row["total"]


@pytest.mark.asyncio
async def test_deleting_a_conversation_leaves_no_checkpoints_and_spares_the_others(
    repository: PostgresThreadRepository, ids: list[str]
) -> None:
    await setup_checkpointer(_settings())
    async with open_checkpointer(_settings()) as checkpointer:
        builder = StateGraph(MessagesState)
        builder.add_node("reply", lambda state: {"messages": []})
        builder.add_edge(START, "reply")
        graph = builder.compile(checkpointer=checkpointer)
        try:
            for thread_id in ids[:2]:
                await repository.record(thread_id, "Hi", FUTURE)
                config: RunnableConfig = {"configurable": {"thread_id": thread_id}}
                await graph.ainvoke({"messages": [HumanMessage("Hi")]}, config)
            untouched = await _checkpoint_rows(ids[1])
            assert await _checkpoint_rows(ids[0]) > 0

            async def delete_saved(thread_id: str) -> None:
                await delete_checkpoints(checkpointer, thread_id)

            await ThreadService(repository, delete_saved).delete(ids[0])

            assert await _checkpoint_rows(ids[0]) == 0
            assert await _checkpoint_rows(ids[1]) == untouched
            assert [t.thread_id for t in await _listed(repository, ids)] == [ids[1]]
        finally:
            for thread_id in ids:
                await checkpointer.adelete_thread(thread_id)
