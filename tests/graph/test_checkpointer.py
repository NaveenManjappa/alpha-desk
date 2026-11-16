"""Tests for the checkpointer factory."""

import logging

import pytest

from alphadesk.domain.answer import AnswerDraft
from alphadesk.graph.checkpointer import create_checkpointer


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
