"""Work out a run's usage and estimated cost. Plain arithmetic, no LangChain.

Why the cost is an estimate, not the bill:

- Prices are copied into settings by hand and can go out of date.
- Providers bill cached input tokens at a lower rate. This counts every input token at
  the full rate, so it errs on the high side.
- Token counts come from the provider's own usage report, so they match the trace and the
  bill. The price applied to them is the only guess.
"""

from collections.abc import Sequence

from alphadesk.domain.usage import ModelPrice, RunUsage

_TOKENS_PER_PRICE_UNIT = 1_000_000

# Enough decimal places for a run that costs a fraction of a cent, without float noise
# such as 0.0011100000000000001.
_COST_DECIMALS = 8


def estimate_cost_usd(input_tokens: int, output_tokens: int, price: ModelPrice) -> float:
    """The estimated cost in US dollars of the given tokens at the given price.

    Example: 3,000 input and 180 output tokens at $0.25 and $2.00 per million cost
    3,000 / 1,000,000 * 0.25 + 180 / 1,000,000 * 2.00 = $0.00111.
    """
    cost = (
        input_tokens * price.input_usd_per_million + output_tokens * price.output_usd_per_million
    ) / _TOKENS_PER_PRICE_UNIT
    return round(cost, _COST_DECIMALS)


def summarise_usage(
    token_counts: Sequence[tuple[int, int]], duration_seconds: float, price: ModelPrice
) -> RunUsage:
    """Add up the model calls of one run into a `RunUsage`.

    Args:
        token_counts: `(input_tokens, output_tokens)` for each model call in the run.
        duration_seconds: How long the whole run took.
        price: The price of the model the run used.
    """
    input_tokens = sum(count[0] for count in token_counts)
    output_tokens = sum(count[1] for count in token_counts)
    return RunUsage(
        duration_seconds=duration_seconds,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        estimated_cost_usd=estimate_cost_usd(input_tokens, output_tokens, price),
    )
