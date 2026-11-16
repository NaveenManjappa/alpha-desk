"""Tests for the checkpointer factories. No database: Postgres is covered by the
integration tests in test_checkpointer_postgres.py."""

import logging

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from alphadesk.config.settings import Settings
from alphadesk.domain.answer import AnswerDraft
from alphadesk.graph.checkpointer import create_checkpointer, open_checkpointer, setup_checkpointer


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, openai_api_key="test-key", **overrides)  # pyright: ignore[reportCallIssue]


@pytest.mark.unit
def test_each_call_returns_a_new_empty_checkpointer() -> None:
    first, second = create_checkpointer(), create_checkpointer()

    assert first is not second
    assert list(first.list(None)) == []


@pytest.mark.unit
def test_an_answer_draft_round_trips_without_an_unsafe_type_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    serde = create_checkpointer().serde
    draft = AnswerDraft(summary="Apple is up.", key_figures=[], sources=[])

    with caplog.at_level(logging.WARNING):
        restored = serde.loads_typed(serde.dumps_typed(draft))

    assert restored == draft
    assert "unregistered type" not in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_memory_setting_opens_an_in_memory_checkpointer() -> None:
    async with open_checkpointer(_settings(checkpointer="memory")) as checkpointer:
        assert isinstance(checkpointer, InMemorySaver)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_setup_without_a_postgres_url_names_the_setting() -> None:
    with pytest.raises(ValueError, match="ALPHADESK_POSTGRES_URL"):
        await setup_checkpointer(_settings())
