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
    """The error a tool returns when `normalise_ticker` rejects its input."""
    return ToolError(
        error_type="invalid_input",
        message=f"'{ticker}' is not a valid ticker. Use a symbol such as 'AAPL'.",
        as_of=datetime.now(UTC),
    )
