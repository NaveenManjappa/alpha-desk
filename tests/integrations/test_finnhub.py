"""Tests for the Finnhub client. httpx.MockTransport answers in memory, so no network."""

from collections.abc import Callable
from datetime import UTC, datetime

import httpx
import pytest

from alphadesk.config.settings import Settings
from alphadesk.domain.market_data import MarketDataError
from alphadesk.integrations.finnhub import FinnhubClient, create_finnhub_http_client

Handler = Callable[[httpx.Request], httpx.Response]


def _client(handler: Handler) -> FinnhubClient:
    http = httpx.AsyncClient(
        base_url="https://finnhub.io/api/v1",
        transport=httpx.MockTransport(handler),
        headers={"X-Finnhub-Token": "secret-key"},
    )
    return FinnhubClient(http)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_quote_calls_quote_endpoint_and_returns_a_neutral_quote() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"c": 227.5, "d": 1.25, "dp": 0.55, "t": 1_762_966_800})

    quote = await _client(handler).get_quote("AAPL")

    assert quote is not None
    assert quote.price == 227.5
    assert quote.change == 1.25
    assert quote.quote_time == datetime.fromtimestamp(1_762_966_800, tz=UTC)
    assert seen[0].url.path == "/api/v1/quote"
    assert seen[0].url.params["symbol"] == "AAPL"
    assert seen[0].headers["X-Finnhub-Token"] == "secret-key"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_finnhub_all_zero_reply_means_unknown_symbol() -> None:
    # Finnhub answers an unknown symbol with 200 OK and zeros, not with a 404.
    zeros = {"c": 0, "d": None, "dp": None, "h": 0, "l": 0, "o": 0, "pc": 0, "t": 0}
    client = _client(lambda _: httpx.Response(200, json=zeros))

    assert await client.get_quote("ZZZZZ") is None


@pytest.mark.unit
def test_quote_url_never_contains_the_api_key() -> None:
    url = _client(lambda _: httpx.Response(200)).quote_url("AAPL")

    assert url == "https://finnhub.io/api/v1/quote?symbol=AAPL"
    assert "secret-key" not in url


@pytest.mark.unit
@pytest.mark.asyncio
async def test_error_status_raises_market_data_error_with_status_code() -> None:
    client = _client(lambda _: httpx.Response(429, json={"error": "rate limit"}))

    with pytest.raises(MarketDataError) as caught:
        await client.get_quote("AAPL")

    assert caught.value.status_code == 429


@pytest.mark.unit
@pytest.mark.asyncio
async def test_timeout_raises_market_data_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    with pytest.raises(MarketDataError, match="in time"):
        await _client(handler).get_quote("AAPL")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unexpected_body_raises_market_data_error() -> None:
    client = _client(lambda _: httpx.Response(200, text="<html>maintenance</html>"))

    with pytest.raises(MarketDataError, match="unexpected shape"):
        await client.get_quote("AAPL")


@pytest.mark.unit
def test_http_client_requires_an_api_key() -> None:
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        openai_api_key="test-key",  # pyright: ignore[reportArgumentType]
    )

    with pytest.raises(ValueError, match="ALPHADESK_FINNHUB_API_KEY"):
        create_finnhub_http_client(settings)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_http_client_sets_base_url_timeout_and_key_header() -> None:
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        openai_api_key="test-key",  # pyright: ignore[reportArgumentType]
        finnhub_api_key="fh-key",  # pyright: ignore[reportArgumentType]
        finnhub_timeout_seconds=3.0,
    )

    async with create_finnhub_http_client(settings) as http:
        assert str(http.base_url) == "https://finnhub.io/api/v1/"
        assert http.timeout.read == 3.0
        assert http.headers["X-Finnhub-Token"] == "fh-key"
