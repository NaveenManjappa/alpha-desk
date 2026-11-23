"""Tests for the run usage and cost estimate. Plain arithmetic, checked by hand."""

import pytest

from alphadesk.domain.usage import ModelPrice
from alphadesk.services.usage import estimate_cost_usd, summarise_usage

# Prices in USD per million tokens.
PRICE = ModelPrice(input_usd_per_million=0.25, output_usd_per_million=2.00)


@pytest.mark.unit
def test_cost_matches_a_hand_worked_example() -> None:
    # 3,000 input tokens:  3,000 / 1,000,000 * $0.25 = $0.00075
    #   180 output tokens:   180 / 1,000,000 * $2.00 = $0.00036
    #                                           total = $0.00111
    assert estimate_cost_usd(input_tokens=3_000, output_tokens=180, price=PRICE) == pytest.approx(
        0.00111
    )


@pytest.mark.unit
def test_no_tokens_cost_nothing() -> None:
    assert estimate_cost_usd(input_tokens=0, output_tokens=0, price=PRICE) == 0.0


@pytest.mark.unit
def test_summary_adds_up_every_model_call_of_the_run() -> None:
    # Two model calls: (1,000 in, 100 out) and (2,000 in, 80 out).
    usage = summarise_usage(
        token_counts=[(1_000, 100), (2_000, 80)], duration_seconds=4.234, price=PRICE
    )

    assert usage.input_tokens == 3_000
    assert usage.output_tokens == 180
    assert usage.total_tokens == 3_180
    assert usage.estimated_cost_usd == pytest.approx(0.00111)
    assert usage.duration_seconds == pytest.approx(4.234)


@pytest.mark.unit
def test_summary_of_a_run_with_no_model_calls_is_all_zero() -> None:
    usage = summarise_usage(token_counts=[], duration_seconds=0.1, price=PRICE)

    assert (usage.input_tokens, usage.output_tokens, usage.total_tokens) == (0, 0, 0)
    assert usage.estimated_cost_usd == 0.0


@pytest.mark.unit
def test_cost_has_no_floating_point_noise() -> None:
    # 0.1 + 0.2 style noise would show up as $0.0011100000000000001 in the UI.
    usage = summarise_usage(token_counts=[(3_000, 180)], duration_seconds=1.0, price=PRICE)

    assert usage.estimated_cost_usd == round(usage.estimated_cost_usd, 8)


@pytest.mark.unit
def test_prices_cannot_be_negative() -> None:
    with pytest.raises(ValueError, match="greater than or equal to 0"):
        ModelPrice(input_usd_per_million=-1, output_usd_per_million=2)
