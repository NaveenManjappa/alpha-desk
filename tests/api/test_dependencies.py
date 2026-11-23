"""Tests for the app's wiring. Builds the real services with an in-memory checkpointer.

Building them opens HTTP clients but sends nothing, so there is no network call.
"""

import pytest

from alphadesk.api.dependencies import create_thread_repository, open_app_services
from alphadesk.config.settings import Settings
from alphadesk.repositories.postgres_threads import PostgresThreadRepository
from alphadesk.repositories.threads import InMemoryThreadRepository


def _settings(**overrides: object) -> Settings:
    return Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        openai_api_key="test-key",  # pyright: ignore[reportArgumentType]
        sec_edgar_user_agent="AlphaDesk test@example.com",
        checkpointer="memory",
        **overrides,  # pyright: ignore[reportArgumentType]
    )


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("key", [None, ""], ids=["unset", "blank"])
async def test_app_starts_without_a_finnhub_key(key: str | None) -> None:
    # Only price questions need Finnhub. Without a key the quote tool explains, and the
    # rest of the desk still works, instead of the whole API refusing to start.
    async with open_app_services(_settings(finnhub_api_key=key)) as services:
        assert services.chat is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_app_starts_with_a_finnhub_key() -> None:
    async with open_app_services(_settings(finnhub_api_key="fh-key")) as services:
        assert services.chat is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_memory_keeps_the_list_in_memory_too() -> None:
    async with open_app_services(_settings()) as services:
        assert isinstance(services.threads, InMemoryThreadRepository)


@pytest.mark.unit
def test_postgres_keeps_the_list_in_postgres_too() -> None:
    settings = _settings(postgres_url="postgresql://localhost/nowhere").model_copy(
        update={"checkpointer": "postgres"}
    )

    # Nothing is connected to: the repository opens a connection only when it is used.
    assert isinstance(create_thread_repository(settings), PostgresThreadRepository)
