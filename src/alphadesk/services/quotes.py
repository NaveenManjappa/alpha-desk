"""Quote logic: validate the ticker, fetch the price, and turn every outcome into data.

This is where our decisions live (what counts as a valid ticker, which outcome becomes
which error). It knows nothing about any particular provider: it speaks only the
domain types, and the client handles the provider's own quirks. The tool in `tools/`
only calls this, so all of it is testable without LangChain.
"""

import logging
from datetime import UTC, datetime
from typing import Protocol

from alphadesk.domain.market_data import MarketDataError, MarketQuote
from alphadesk.domain.tool_results import QuoteResult, ToolError
from alphadesk.services.tickers import invalid_ticker_error, normalise_ticker

logger = logging.getLogger(__name__)


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


# HTTP statuses that mean the provider refused our key. Retrying will not help.
_KEY_REJECTED = {401, 403}


class QuoteService:
    """Gets share prices. Never raises for an expected failure; returns a `ToolError`."""

    def __init__(self, source: QuoteSource | None) -> None:
        """Args:
        source: The market data client, passed in so tests can supply a fake. None when
            no market data key is configured: every price question then gets an
            "unavailable" error, and the rest of the app works as normal.
        """
        self._source = source

    async def get_quote(self, ticker: str) -> QuoteResult | ToolError:
        """Return the latest quote for a ticker, or a typed error saying why not.

        Args:
            ticker: A US ticker symbol. Case and surrounding spaces are ignored.
        """
        symbol = normalise_ticker(ticker)
        if symbol is None:
            return invalid_ticker_error(ticker)
        if self._source is None:
            return ToolError(
                error_type="unavailable",
                message="Share prices are not available: the price service is not set up.",
                as_of=datetime.now(UTC),
            )

        source_url = self._source.quote_url(symbol)
        try:
            quote = await self._source.get_quote(symbol)
        except MarketDataError as exc:
            logger.warning("Quote for %s failed: %s", symbol, exc)
            return _quote_failed(symbol, source_url, exc)
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


def _quote_failed(symbol: str, source_url: str, error: MarketDataError) -> ToolError:
    """The error to hand the model when the provider failed, after any retries."""
    if error.status_code in _KEY_REJECTED:
        return ToolError(
            error_type="unavailable",
            message="Share prices are not available: the price service refused our API key.",
            source_url=source_url,
            as_of=datetime.now(UTC),
        )
    return ToolError(
        error_type="upstream_error",
        message=f"The price service failed for {symbol}. Try again later.",
        source_url=source_url,
        as_of=datetime.now(UTC),
    )
