"""Tests for the in-memory thread repository."""

from datetime import UTC, datetime, timedelta

import pytest

from alphadesk.domain.thread import ThreadSummary
from alphadesk.repositories.threads import InMemoryThreadRepository

NOON = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_recorded_thread_is_listed() -> None:
    repository = InMemoryThreadRepository()

    await repository.record("apple", "How is Apple?", NOON)

    assert await repository.list_recent(50) == [
        ThreadSummary(thread_id="apple", title="How is Apple?", last_used_at=NOON)
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_recording_again_keeps_the_title_and_moves_the_time() -> None:
    repository = InMemoryThreadRepository()
    later = NOON + timedelta(minutes=5)

    await repository.record("apple", "How is Apple?", NOON)
    await repository.record("apple", "And its revenue?", later)

    assert await repository.list_recent(50) == [
        ThreadSummary(thread_id="apple", title="How is Apple?", last_used_at=later)
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_newest_first_and_a_used_thread_moves_to_the_top() -> None:
    repository = InMemoryThreadRepository()
    await repository.record("apple", "Apple?", NOON)
    await repository.record("nvidia", "Nvidia?", NOON + timedelta(minutes=1))
    assert [t.thread_id for t in await repository.list_recent(50)] == ["nvidia", "apple"]

    await repository.record("apple", "More Apple?", NOON + timedelta(minutes=2))

    assert [t.thread_id for t in await repository.list_recent(50)] == ["apple", "nvidia"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_the_limit_keeps_the_newest() -> None:
    repository = InMemoryThreadRepository()
    for minute in range(3):
        await repository.record(f"t{minute}", "Hi", NOON + timedelta(minutes=minute))

    assert [t.thread_id for t in await repository.list_recent(2)] == ["t2", "t1"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_removes_one_thread_and_leaves_the_others() -> None:
    repository = InMemoryThreadRepository()
    await repository.record("apple", "Apple?", NOON)
    await repository.record("nvidia", "Nvidia?", NOON)

    await repository.delete("apple")

    assert [t.thread_id for t in await repository.list_recent(50)] == ["nvidia"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_deleting_an_unknown_thread_succeeds() -> None:
    await InMemoryThreadRepository().delete("nobody")
