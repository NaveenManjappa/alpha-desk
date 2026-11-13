"""Filings logic: choose which of a company's recent filings to show.

EDGAR lists every form a company files, including ones we do not use (insider trades,
proxy statements). We keep the latest annual report, the latest quarterly report and a
few recent event notices. Only metadata and links; never the filings' text.
"""

import logging
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Protocol

from alphadesk.domain.filings import Filing, FilingsDataError
from alphadesk.domain.tool_results import RecentFilingsResult, ToolError
from alphadesk.services.tickers import invalid_ticker_error, normalise_ticker

logger = logging.getLogger(__name__)

# How many of each form to return: the latest 10-K (annual report), the latest 10-Q
# (quarterly report) and the five latest 8-Ks (event notices, which are frequent).
_WANTED_FORMS = {"10-K": 1, "10-Q": 1, "8-K": 5}


class FilingsSource(Protocol):
    """What the service needs from a filings client. `EdgarClient` fits it, as does the
    fake in the tests."""

    def submissions_url(self, cik: int) -> str:
        """The address the filing list comes from, shown to the user as the source."""
        ...

    async def get_cik(self, ticker: str) -> int | None:
        """The provider's company ID for a ticker, or None if unknown.

        Raises:
            FilingsDataError: If the provider could not answer.
        """
        ...

    async def get_recent_filings(self, cik: int) -> list[Filing] | None:
        """The company's recent filings of every form, or None if it has no record.

        Raises:
            FilingsDataError: If the provider could not answer.
        """
        ...


class FilingsService:
    """Lists a company's recent key filings. Never raises for an expected failure."""

    def __init__(self, source: FilingsSource) -> None:
        """Args:
        source: The filings client, passed in so tests can supply a fake.
        """
        self._source = source

    async def list_recent_filings(self, ticker: str) -> RecentFilingsResult | ToolError:
        """Return the latest 10-K, 10-Q and 8-K filings, or a typed error saying why not.

        Args:
            ticker: A US ticker symbol. Case and surrounding spaces are ignored.
        """
        symbol = normalise_ticker(ticker)
        if symbol is None:
            return invalid_ticker_error(ticker)

        source_url: str | None = None
        try:
            cik = await self._source.get_cik(symbol)
            if cik is None:
                return ToolError(
                    error_type="not_found",
                    message=f"SEC EDGAR has no company with ticker '{symbol}'.",
                    as_of=datetime.now(UTC),
                )
            source_url = self._source.submissions_url(cik)
            all_filings = await self._source.get_recent_filings(cik)
        except FilingsDataError as exc:
            logger.warning("Filings for %s failed: %s", symbol, exc)
            return ToolError(
                error_type="upstream_error",
                message=f"SEC EDGAR failed for {symbol}. Try again later.",
                source_url=source_url,
                as_of=datetime.now(UTC),
            )
        as_of = datetime.now(UTC)

        filings = _latest_key_filings(all_filings or [])
        if not filings:
            return ToolError(
                error_type="not_found",
                message=f"SEC EDGAR has no recent 10-K, 10-Q or 8-K filings for {symbol}.",
                source_url=source_url,
                as_of=as_of,
            )
        return RecentFilingsResult(
            ticker=symbol, filings=filings, source_url=source_url, as_of=as_of
        )


def _latest_key_filings(filings: Sequence[Filing]) -> list[Filing]:
    """Up to the wanted number of each form, newest first. Amendments ("10-K/A") are skipped."""
    taken: Counter[str] = Counter()
    picked: list[Filing] = []
    for filing in sorted(filings, key=lambda f: f.filing_date, reverse=True):
        limit = _WANTED_FORMS.get(filing.form, 0)
        if taken[filing.form] < limit:
            picked.append(filing)
            taken[filing.form] += 1
    return picked
