"""Integration tests for the Postgres health check, against a real database.

Skipped unless TEST_POSTGRES_URL is set, so `make check` never needs Docker. To run:

    docker compose up -d
    TEST_POSTGRES_URL=postgresql://alphadesk:alphadesk@localhost:5433/alphadesk \\
        uv run pytest -m integration
"""

import os

import pytest

from alphadesk.config.settings import Settings
from alphadesk.integrations.postgres import postgres_is_reachable

# Not an ALPHADESK_ variable: the shared conftest removes those before every test.
POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not POSTGRES_URL, reason="TEST_POSTGRES_URL is not set"),
]


def _settings(postgres_url: str | None) -> Settings:
    return Settings(_env_file=None, openai_api_key="test-key", postgres_url=postgres_url)  # pyright: ignore[reportCallIssue, reportArgumentType]


@pytest.mark.asyncio
async def test_running_database_is_reachable() -> None:
    assert await postgres_is_reachable(_settings(POSTGRES_URL)) is True


@pytest.mark.asyncio
async def test_wrong_password_is_reported_as_unreachable() -> None:
    assert POSTGRES_URL is not None
    bad_url = POSTGRES_URL.replace("alphadesk:alphadesk@", "alphadesk:wrong@")

    assert await postgres_is_reachable(_settings(bad_url)) is False
