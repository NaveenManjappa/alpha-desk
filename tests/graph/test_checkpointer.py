"""Tests for the checkpointer factories. No database: Postgres is covered by the
integration tests in test_checkpointer_postgres.py."""

import logging

import psycopg
import pytest
from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import START, MessagesState, StateGraph

from alphadesk.config.settings import Settings
from alphadesk.domain.answer import AnswerDraft
from alphadesk.domain.errors import StorageError
from alphadesk.graph.checkpointer import (
    create_checkpointer,
    delete_checkpoints,
    open_checkpointer,
    setup_checkpointer,
)


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


def _config(thread_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id}}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_delete_removes_one_thread_and_leaves_the_others() -> None:
    checkpointer = create_checkpointer()
    builder = StateGraph(MessagesState)
    builder.add_node("reply", lambda state: {"messages": []})
    builder.add_edge(START, "reply")
    graph = builder.compile(checkpointer=checkpointer)
    for thread_id in ("apple", "nvidia"):
        await graph.ainvoke({"messages": [HumanMessage("Hi")]}, _config(thread_id))

    await delete_checkpoints(checkpointer, "apple")
    await delete_checkpoints(checkpointer, "nobody")

    assert (await graph.aget_state(_config("apple"))).values == {}
    assert len((await graph.aget_state(_config("nvidia"))).values["messages"]) == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_failed_delete_becomes_a_storage_error_without_the_details() -> None:
    class BrokenSaver(InMemorySaver):
        async def adelete_thread(self, thread_id: str) -> None:
            raise psycopg.OperationalError("on host db.internal")

    with pytest.raises(StorageError) as caught:
        await delete_checkpoints(BrokenSaver(), "apple")

    assert str(caught.value) == "OperationalError"
