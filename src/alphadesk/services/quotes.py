"""Quote logic: validate the ticker, fetch the price, and turn every outcome into data.

This is where our decisions live (what counts as a valid ticker, which outcome becomes
which error). It knows nothing about any particular provider: it speaks only the
domain types, and the client handles the provider's own quirks. The tool in `tools/`
only calls this, so all of it is testable without LangChain.
"""

import logging
import re
from datetime import UTC, datetime
from typing import Protocol

from alphadesk.domain.market_data import MarketDataError, MarketQuote
from alphadesk.domain.tool_results import QuoteResult, ToolError

logger = logging.getLogger(__name__)

# US tickers: a letter, then up to nine letters, digits, dots or dashes (e.g. "BRK.B").
_TICKER_PATTERN = re.compile(r"[A-Z][A-Z0-9.\-]{0,9}")


class QuoteSource(Protocol):
    """What the service needs from a market data client. `FinnhubClient` fits it, and so
    does the fake in the tests. A Protocol checks the shape without needing inheritance."""

    def quote_url(self, symbol: str) -> str:
        """The address the quote comes from, shown to the user as the source."""
        ...

    async def get_quote(self, symbol: str) -> MarketQuote | None:
        """The latest quote, or None if the symbol does not exist.

        Raises:
            MarketDataError: If the provider could not answer.
        """
        ...


class QuoteService:
    """Gets share prices. Never raises for an expected failure; returns a `ToolError`."""

    def __init__(self, source: QuoteSource) -> None:
        """Args:
        source: The market data client, passed in so tests can supply a fake.
        """
        self._source = source

    async def get_quote(self, ticker: str) -> QuoteResult | ToolError:
        """Return the latest quote for a ticker, or a typed error saying why not.

        Args:
            ticker: A US ticker symbol. Case and surrounding spaces are ignored.
        """
        symbol = ticker.strip().upper()
        if not _TICKER_PATTERN.fullmatch(symbol):
            return ToolError(
                error_type="invalid_input",
                message=f"'{ticker}' is not a valid ticker. Use a symbol such as 'AAPL'.",
                as_of=datetime.now(UTC),
            )

        source_url = self._source.quote_url(symbol)
        try:
            quote = await self._source.get_quote(symbol)
        except MarketDataError as exc:
            logger.warning("Quote for %s failed: %s", symbol, exc)
            return ToolError(
                error_type="upstream_error",
                message=f"The price service failed for {symbol}. Try again later.",
                source_url=source_url,
                as_of=datetime.now(UTC),
            )
        as_of = datetime.now(UTC)

        if quote is None:
            return ToolError(
                error_type="not_found",
                message=f"No quote found for '{symbol}'. Check it is a US-listed ticker.",
                source_url=source_url,
                as_of=as_of,
            )

        return QuoteResult(
            ticker=symbol,
            price=quote.price,
            change=quote.change,
            quote_time=quote.quote_time,
            source_url=source_url,
            as_of=as_of,
        )
