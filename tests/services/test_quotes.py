"""Tests for QuoteService, with a fake market data client. No network, no provider types."""

from datetime import UTC, datetime

import pytest

from alphadesk.domain.market_data import MarketDataError, MarketQuote
from alphadesk.domain.tool_results import QuoteResult, ToolError
from alphadesk.services.quotes import QuoteService

QUOTE_TIME = datetime(2026, 11, 12, 20, 0, tzinfo=UTC)
APPLE_QUOTE = MarketQuote(price=227.5, change=1.25, quote_time=QUOTE_TIME)


class FakeQuoteSource:
    """Returns a canned quote (or None for "no such symbol"), or raises a canned error.
    Records the symbols asked for."""

    def __init__(self, quote: MarketQuote | None = None, error: Exception | None = None) -> None:
        self.quote = quote
        self.error = error
        self.calls: list[str] = []

    def quote_url(self, symbol: str) -> str:
        return f"https://market.example/quote?symbol={symbol}"

    async def get_quote(self, symbol: str) -> MarketQuote | None:
        self.calls.append(symbol)
        if self.error is not None:
            raise self.error
        return self.quote


@pytest.mark.unit
@pytest.mark.asyncio
async def test_known_ticker_returns_a_quote_with_timestamp_and_source() -> None:
    service = QuoteService(FakeQuoteSource(quote=APPLE_QUOTE))

    result = await service.get_quote("AAPL")

    assert isinstance(result, QuoteResult)
    assert result.ticker == "AAPL"
    assert result.price == 227.5
    assert result.change == 1.25
    assert result.quote_time == QUOTE_TIME
    assert result.source_url == "https://market.example/quote?symbol=AAPL"
    assert result.as_of.tzinfo is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ticker_is_normalised_before_the_call() -> None:
    source = FakeQuoteSource(quote=APPLE_QUOTE)

    result = await QuoteService(source).get_quote("  brk.b ")

    assert isinstance(result, QuoteResult)
    assert source.calls == ["BRK.B"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unknown_ticker_returns_not_found_error() -> None:
    service = QuoteService(FakeQuoteSource(quote=None))

    result = await service.get_quote("ZZZZZ")

    assert isinstance(result, ToolError)
    assert result.error_type == "not_found"
    assert "ZZZZZ" in result.message
    assert result.source_url is not None


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("bad_ticker", ["", "   ", "123", "AAPL; DROP", "WAYTOOLONGTICKER"])
async def test_bad_input_returns_invalid_input_without_calling_upstream(bad_ticker: str) -> None:
    source = FakeQuoteSource(quote=APPLE_QUOTE)

    result = await QuoteService(source).get_quote(bad_ticker)

    assert isinstance(result, ToolError)
    assert result.error_type == "invalid_input"
    assert source.calls == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upstream_failure_returns_upstream_error_instead_of_raising() -> None:
    error = MarketDataError("Provider returned HTTP 503", status_code=503)
    service = QuoteService(FakeQuoteSource(error=error))

    result = await service.get_quote("AAPL")

    assert isinstance(result, ToolError)
    assert result.error_type == "upstream_error"
    # The message is ours, not upstream's text: retrieved text is data, not instructions.
    assert "503" not in result.message
