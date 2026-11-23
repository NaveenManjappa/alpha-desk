"""Ticker rules shared by every tool that takes a ticker.

Three services now validate tickers the same way, so the rule lives here once.
"""

import re
from datetime import UTC, datetime

from alphadesk.domain.tool_results import ToolError

# US tickers: a letter, then up to nine letters, digits, dots or dashes (e.g. "BRK.B").
_TICKER_PATTERN = re.compile(r"[A-Z][A-Z0-9.\-]{0,9}")


def normalise_ticker(ticker: str) -> str | None:
    """Return the ticker upper-cased and trimmed, or None if it cannot be a US ticker."""
    symbol = ticker.strip().upper()
    return symbol if _TICKER_PATTERN.fullmatch(symbol) else None


def invalid_ticker_error(ticker: str) -> ToolError:
    """The error a tool returns when `normalise_ticker` rejects its input.

    The message names no example ticker. An earlier one did ("such as 'AAPL'"), and a
    model asked an off-topic question took it as a hint, then fetched Apple's quote over
    and over until the run limit stopped it. The message says what to do instead.
    """
    return ToolError(
        error_type="invalid_input",
        message=(
            f"'{ticker}' is not a valid US ticker. Do not guess one. If the question names "
            "no company, call no more tools and say so in your answer."
        ),
        as_of=datetime.now(UTC),
    )
