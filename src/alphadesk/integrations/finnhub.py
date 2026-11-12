"""A small async client for Finnhub's market data API (ADR 007).

This module is the only place that knows Finnhub: its URLs, auth, response shape and
quirks. It translates all of that into the provider-neutral types in
`domain/market_data.py`, so nothing outside this file changes if the provider does.
"""

import logging
from datetime import UTC, datetime

import httpx
from pydantic import BaseModel, Field, ValidationError

from alphadesk.config.settings import Settings
from alphadesk.domain.market_data import MarketDataError, MarketQuote

logger = logging.getLogger(__name__)


class _FinnhubQuote(BaseModel):
    """Finnhub's raw `/quote` response, with readable names. Private to this module.

    Finnhub uses one-letter keys; `alias` maps them. For an unknown symbol Finnhub still
    answers 200, with zeros for the numbers and null for the change fields.
    """

    current_price: float = Field(alias="c")
    change: float | None = Field(alias="d")
    timestamp: int = Field(alias="t")  # Unix seconds, UTC


def create_finnhub_http_client(settings: Settings) -> httpx.AsyncClient:
    """Build the HTTP client for Finnhub, with base URL, timeout and API key set.

    The key goes in a header, not the query string, so it never appears in URLs,
    logs or the `source_url` we show to the model.
    Use it as a context manager so the connection pool is closed:
    `async with create_finnhub_http_client(settings) as http: ...`

    Raises:
        ValueError: If ALPHADESK_FINNHUB_API_KEY is not set.
    """
    if settings.finnhub_api_key is None:
        raise ValueError("ALPHADESK_FINNHUB_API_KEY is missing. Set it in the environment or .env.")
    return httpx.AsyncClient(
        base_url=settings.finnhub_base_url,
        timeout=settings.finnhub_timeout_seconds,
        headers={"X-Finnhub-Token": settings.finnhub_api_key.get_secret_value()},
    )


class FinnhubClient:
    """Calls Finnhub endpoints and returns provider-neutral results."""

    def __init__(self, http: httpx.AsyncClient) -> None:
        """Wrap an HTTP client built by `create_finnhub_http_client` (or a fake in tests)."""
        self._http = http

    def quote_url(self, symbol: str) -> str:
        """The `/quote` URL for a symbol. Safe to show: the key is sent as a header."""
        return str(self._http.build_request("GET", "/quote", params={"symbol": symbol}).url)

    async def get_quote(self, symbol: str) -> MarketQuote | None:
        """Fetch the latest quote for one symbol.

        Returns:
            The quote, or None if Finnhub has no such symbol.

        Raises:
            MarketDataError: On timeout, network failure, a non-2xx status or an unexpected body.
        """
        raw = await self._fetch_quote(symbol)
        # Finnhub's way of saying "unknown symbol": a zero timestamp and no change.
        if raw.timestamp == 0 or raw.change is None:
            return None
        return MarketQuote(
            price=raw.current_price,
            change=raw.change,
            quote_time=datetime.fromtimestamp(raw.timestamp, tz=UTC),
        )

    async def _fetch_quote(self, symbol: str) -> _FinnhubQuote:
        """Call `/quote` and validate the body, turning every failure into MarketDataError."""
        try:
            response = await self._http.get("/quote", params={"symbol": symbol})
            response.raise_for_status()
            return _FinnhubQuote.model_validate_json(response.content)
        except httpx.TimeoutException as exc:
            raise MarketDataError("Finnhub did not answer in time") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            raise MarketDataError(f"Finnhub returned HTTP {status}", status_code=status) from exc
        except httpx.RequestError as exc:
            raise MarketDataError(f"Could not reach Finnhub: {type(exc).__name__}") from exc
        except ValidationError as exc:
            raise MarketDataError("Finnhub sent a response in an unexpected shape") from exc
