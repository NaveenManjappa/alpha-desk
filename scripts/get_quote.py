"""Smoke test for Slice 3: fetch a real quote through the service and log it.

Run with: uv run python scripts/get_quote.py AAPL
Makes one real Finnhub call. Needs ALPHADESK_FINNHUB_API_KEY.
"""

import asyncio
import logging
import sys

from alphadesk.config.settings import get_settings
from alphadesk.integrations.finnhub import FinnhubClient, create_finnhub_http_client
from alphadesk.services.quotes import QuoteService

logger = logging.getLogger(__name__)


async def main(ticker: str) -> None:
    """Fetch one quote and log the typed result (or typed error)."""
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(message)s")

    async with create_finnhub_http_client(settings) as http:
        service = QuoteService(FinnhubClient(http))
        result = await service.get_quote(ticker)
    logger.info("%s", result.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "AAPL"))
