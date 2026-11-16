"""Integration tests for the Postgres checkpointer, against a real database.

Skipped unless TEST_POSTGRES_URL is set, so `make check` never needs Docker. To run:

    docker compose up -d
    TEST_POSTGRES_URL=postgresql://alphadesk:alphadesk@localhost:5433/alphadesk \\
        uv run pytest -m integration

No LLM: a one-node graph stands in for the agent. What is under test is that state
written through one connection can be read back through a new one, as after a restart.
"""

import os
from typing import Annotated, Any, TypedDict
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import START, StateGraph
from langgraph.graph.message import add_messages

from alphadesk.config.settings import Settings
from alphadesk.domain.answer import AnswerDraft
from alphadesk.graph.checkpointer import open_checkpointer, setup_checkpointer

# Not an ALPHADESK_ variable: the shared conftest removes those before every test.
POSTGRES_URL = os.environ.get("TEST_POSTGRES_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not POSTGRES_URL, reason="TEST_POSTGRES_URL is not set"),
]

DRAFT = AnswerDraft(summary="Apple is up.", key_figures=[], sources=[])


class _State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]
    structured_response: AnswerDraft | None


def _reply(state: _State) -> dict[str, Any]:
    return {"messages": [AIMessage("Apple is up.")], "structured_response": DRAFT}


def _graph(checkpointer: BaseCheckpointSaver) -> Any:
    builder = StateGraph(_State)
    builder.add_node("reply", _reply)
    builder.add_edge(START, "reply")
    return builder.compile(checkpointer=checkpointer)


def _settings() -> Settings:
    overrides = {"openai_api_key": "test-key", "checkpointer": "postgres"}
    return Settings(_env_file=None, postgres_url=POSTGRES_URL, **overrides)  # pyright: ignore[reportCallIssue]


@pytest.mark.asyncio
async def test_setup_can_run_twice() -> None:
    await setup_checkpointer(_settings())
    await setup_checkpointer(_settings())


@pytest.mark.asyncio
async def test_a_thread_survives_closing_and_reopening_the_checkpointer() -> None:
    settings = _settings()
    await setup_checkpointer(settings)
    thread_id = f"test-{uuid4().hex}"
    config: RunnableConfig = {"configurable": {"thread_id": thread_id}}

    # First "run" of the program: one turn, then the connection is closed.
    async with open_checkpointer(settings) as checkpointer:
        await _graph(checkpointer).ainvoke({"messages": [HumanMessage("How is Apple?")]}, config)

    # Second "run": a new connection sees the same thread.
    async with open_checkpointer(settings) as checkpointer:
        try:
            snapshot = await _graph(checkpointer).aget_state(config)
            assert [m.text for m in snapshot.values["messages"]] == [
                "How is Apple?",
                "Apple is up.",
            ]
            assert snapshot.values["structured_response"] == DRAFT
        finally:
            await checkpointer.adelete_thread(thread_id)


@pytest.mark.asyncio
async def test_an_unknown_thread_has_no_state() -> None:
    settings = _settings()
    await setup_checkpointer(settings)
    config: RunnableConfig = {"configurable": {"thread_id": f"test-{uuid4().hex}"}}

    async with open_checkpointer(settings) as checkpointer:
        snapshot = await _graph(checkpointer).aget_state(config)

    assert snapshot.values == {}
