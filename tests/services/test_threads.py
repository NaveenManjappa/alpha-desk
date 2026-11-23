"""Tests for ThreadService. Fakes record the order of the two deletes: no database."""

from datetime import UTC, datetime

import pytest

from alphadesk.domain.errors import StorageError
from alphadesk.repositories.threads import InMemoryThreadRepository
from alphadesk.services.threads import ThreadService

NOW = datetime(2026, 11, 23, 12, 0, tzinfo=UTC)


class RecordingRepository(InMemoryThreadRepository):
    """Adds a line to `steps` for each delete."""

    def __init__(self, steps: list[str]) -> None:
        super().__init__()
        self.steps = steps

    async def delete(self, thread_id: str) -> None:
        self.steps.append(f"row {thread_id}")
        await super().delete(thread_id)


class FakeCheckpoints:
    """Stands in for deleting the checkpoints. Fails with `error`, if one is given."""

    def __init__(self, steps: list[str], error: Exception | None = None) -> None:
        self.steps = steps
        self.error = error

    async def delete(self, thread_id: str) -> None:
        self.steps.append(f"checkpoints {thread_id}")
        if self.error is not None:
            raise self.error


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_removes_the_checkpoints_before_the_row() -> None:
    steps: list[str] = []
    repository = RecordingRepository(steps)
    await repository.record("apple", "Apple?", NOW)
    await repository.record("nvidia", "Nvidia?", NOW)

    await ThreadService(repository, FakeCheckpoints(steps).delete).delete("apple")

    assert steps == ["checkpoints apple", "row apple"]
    assert [t.thread_id for t in await repository.list_recent(50)] == ["nvidia"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_failed_checkpoint_delete_keeps_the_row() -> None:
    steps: list[str] = []
    repository = RecordingRepository(steps)
    await repository.record("apple", "Apple?", NOW)
    checkpoints = FakeCheckpoints(steps, StorageError("OperationalError"))

    with pytest.raises(StorageError):
        await ThreadService(repository, checkpoints.delete).delete("apple")

    assert [t.thread_id for t in await repository.list_recent(50)] == ["apple"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_deleting_an_unknown_thread_succeeds_every_time() -> None:
    service = ThreadService(InMemoryThreadRepository(), FakeCheckpoints([]).delete)

    await service.delete("nobody")
    await service.delete("nobody")
