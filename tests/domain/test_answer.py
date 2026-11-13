"""Tests for the answer contract's validation rules."""

from typing import Any

import pytest
from pydantic import ValidationError

from alphadesk.domain.answer import AnswerDraft, KeyFigure

PRICE: dict[str, Any] = {
    "label": "Share price",
    "value": 227.5,
    "unit": "USD",
    "period": "2026-11-12 16:20 UTC",
    "source_url": "https://finnhub.io/api/v1/quote?symbol=AAPL",
}


@pytest.mark.unit
def test_key_figure_with_every_field_is_valid() -> None:
    assert KeyFigure.model_validate(PRICE).value == 227.5


@pytest.mark.unit
@pytest.mark.parametrize("missing", ["label", "value", "unit", "period", "source_url"])
def test_key_figure_needs_every_field(missing: str) -> None:
    figure = {key: value for key, value in PRICE.items() if key != missing}

    with pytest.raises(ValidationError, match=missing):
        KeyFigure.model_validate(figure)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("field", "bad_value"),
    [("label", ""), ("source_url", "finnhub quote"), ("value", float("nan"))],
)
def test_key_figure_rejects_bad_values(field: str, bad_value: object) -> None:
    with pytest.raises(ValidationError, match=field):
        KeyFigure.model_validate({**PRICE, field: bad_value})


@pytest.mark.unit
def test_draft_ignores_fields_only_code_may_set() -> None:
    draft = AnswerDraft.model_validate(
        {"summary": "Up today.", "key_figures": [], "sources": [], "disclaimer": "Buy!"}
    )

    assert "disclaimer" not in draft.model_dump()
