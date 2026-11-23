"""Tests for finalise_answer: code, not the model, sets as_of, verified and the disclaimer."""

from datetime import UTC, datetime

import pytest

from alphadesk.domain.answer import DISCLAIMER, AnswerDraft, KeyFigure
from alphadesk.services.answers import finalise_answer

ANSWERED_AT = datetime(2026, 11, 13, 9, 0, 5, tzinfo=UTC)
REVENUE = KeyFigure(
    label="Revenue",
    value=245_122_000_000,
    unit="USD",
    period="FY2025",
    source_url="https://www.sec.gov/Archives/edgar/data/789019/000095017025100235/",
)
DRAFT = AnswerDraft(
    summary="Microsoft's revenue grew last year.",
    key_figures=[REVENUE],
    sources=[REVENUE.source_url],
)


@pytest.mark.unit
def test_keeps_the_model_written_fields() -> None:
    answer = finalise_answer(DRAFT, data_fetched_at=[ANSWERED_AT], answered_at=ANSWERED_AT)

    assert answer.summary == DRAFT.summary
    assert answer.key_figures == [REVENUE]
    assert answer.sources == DRAFT.sources


@pytest.mark.unit
def test_always_sets_the_fixed_disclaimer_and_unverified() -> None:
    answer = finalise_answer(DRAFT, data_fetched_at=[], answered_at=ANSWERED_AT)

    assert answer.disclaimer == DISCLAIMER
    assert answer.verified is False


@pytest.mark.unit
def test_as_of_is_the_oldest_tool_fetch_time() -> None:
    older = datetime(2026, 11, 13, 9, 0, 1, tzinfo=UTC)
    newer = datetime(2026, 11, 13, 9, 0, 3, tzinfo=UTC)

    answer = finalise_answer(DRAFT, data_fetched_at=[newer, older], answered_at=ANSWERED_AT)

    assert answer.as_of == older


@pytest.mark.unit
def test_as_of_falls_back_to_answer_time_when_no_tool_ran() -> None:
    draft = AnswerDraft(summary="Two plus two is four.", key_figures=[], sources=[])

    answer = finalise_answer(draft, data_fetched_at=[], answered_at=ANSWERED_AT)

    assert answer.as_of == ANSWERED_AT
