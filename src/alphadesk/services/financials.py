"""Financial facts logic: pick each company's recent annual figures out of everything it reported.

EDGAR returns every value a company ever reported for a concept: quarterly and annual,
original and restated, plus last year's figures repeated in this year's 10-K. The rules
here choose one clean number per metric per fiscal year. They know nothing about EDGAR's
URLs or JSON; the client handles those.
"""

import logging
from collections.abc import Iterable, Sequence
from datetime import UTC, date, datetime
from typing import Literal, Protocol

from alphadesk.domain.filings import FilingsDataError, ReportedFact
from alphadesk.domain.tool_results import FinancialFact, FinancialFactsResult, Metric, ToolError
from alphadesk.services.tickers import invalid_ticker_error, normalise_ticker

logger = logging.getLogger(__name__)

# How many recent fiscal years to return.
YEARS = 3

# Companies tag the same figure with different US-GAAP concepts, and switch over time
# (e.g. "SalesRevenueNet" before 2018). We try each and keep the one with the newest year.
# Earlier in the list wins a tie.
_CONCEPTS: dict[Metric, tuple[str, ...]] = {
    "revenue": (
        "Revenues",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueNet",
    ),
    "net_income": ("NetIncomeLoss", "ProfitLoss"),
    "eps_diluted": ("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"),
}

# The XBRL unit we accept for each metric, and how we show it.
_XBRL_UNITS: dict[Metric, str] = {
    "revenue": "USD",
    "net_income": "USD",
    "eps_diluted": "USD/shares",
}
_DISPLAY_UNITS: dict[Metric, Literal["USD", "USD per share"]] = {
    "revenue": "USD",
    "net_income": "USD",
    "eps_diluted": "USD per share",
}

_ANNUAL_FORMS = {"10-K", "10-K/A"}
# A fiscal year is 52 or 53 weeks (364 or 371 days) or a calendar year. A 10-K also
# reports quarters, so this range keeps full years only.
_MIN_YEAR_DAYS = 350
_MAX_YEAR_DAYS = 380


class FinancialFactsSource(Protocol):
    """What the service needs from a filings client. `EdgarClient` fits it, as does the
    fake in the tests."""

    def company_facts_url(self, cik: int) -> str:
        """The address the figures come from, shown to the user as the source."""
        ...

    async def get_cik(self, ticker: str) -> int | None:
        """The provider's company ID for a ticker, or None if unknown.

        Raises:
            FilingsDataError: If the provider could not answer.
        """
        ...

    async def get_reported_facts(
        self, cik: int, concepts: Sequence[str]
    ) -> list[ReportedFact] | None:
        """Every reported value of these concepts, or None if the company has no data.

        Raises:
            FilingsDataError: If the provider could not answer.
        """
        ...


class FinancialFactsService:
    """Gets annual revenue, net income and EPS. Never raises for an expected failure."""

    def __init__(self, source: FinancialFactsSource) -> None:
        """Args:
        source: The filings client, passed in so tests can supply a fake.
        """
        self._source = source

    async def get_financial_facts(self, ticker: str) -> FinancialFactsResult | ToolError:
        """Return the last few fiscal years of key figures, or a typed error saying why not.

        Args:
            ticker: A US ticker symbol. Case and surrounding spaces are ignored.
        """
        symbol = normalise_ticker(ticker)
        if symbol is None:
            return invalid_ticker_error(ticker)

        all_concepts = [concept for concepts in _CONCEPTS.values() for concept in concepts]
        source_url: str | None = None
        try:
            cik = await self._source.get_cik(symbol)
            if cik is None:
                return ToolError(
                    error_type="not_found",
                    message=f"SEC EDGAR has no company with ticker '{symbol}'.",
                    as_of=datetime.now(UTC),
                )
            source_url = self._source.company_facts_url(cik)
            reported = await self._source.get_reported_facts(cik, all_concepts)
        except FilingsDataError as exc:
            logger.warning("Financial facts for %s failed: %s", symbol, exc)
            return ToolError(
                error_type="upstream_error",
                message=f"SEC EDGAR failed for {symbol}. Try again later.",
                source_url=source_url,
                as_of=datetime.now(UTC),
            )
        as_of = datetime.now(UTC)

        facts = [fact for metric in _CONCEPTS for fact in _recent_annual(metric, reported or [])]
        if not facts:
            return ToolError(
                error_type="not_found",
                message=f"SEC EDGAR has no annual 10-K figures for {symbol}.",
                source_url=source_url,
                as_of=as_of,
            )
        return FinancialFactsResult(ticker=symbol, facts=facts, source_url=source_url, as_of=as_of)


def _recent_annual(metric: Metric, reported: Sequence[ReportedFact]) -> list[FinancialFact]:
    """The newest `YEARS` annual values of one metric, newest first, from its best concept."""
    best: list[ReportedFact] = []
    for concept in _CONCEPTS[metric]:
        candidates = (f for f in reported if f.concept == concept and f.unit == _XBRL_UNITS[metric])
        years = _one_per_year(candidates)
        if years and (not best or years[0].period_end > best[0].period_end):
            best = years

    return [
        FinancialFact(
            metric=metric,
            value=fact.value,
            unit=_DISPLAY_UNITS[metric],
            period_start=fact.period_start,
            period_end=fact.period_end,
            source_url=fact.filing_url,
        )
        for fact in best[:YEARS]
        if fact.period_start is not None  # always true after _one_per_year; narrows the type
    ]


def _one_per_year(facts: Iterable[ReportedFact]) -> list[ReportedFact]:
    """Full-year 10-K values, one per fiscal year, newest year first.

    When a year was reported more than once, the most recently filed value wins, so a
    restated figure replaces the original.
    """
    by_year_end: dict[date, ReportedFact] = {}
    for fact in facts:
        if not _is_full_year_from_10k(fact):
            continue
        current = by_year_end.get(fact.period_end)
        if current is None or fact.filed > current.filed:
            by_year_end[fact.period_end] = fact
    return sorted(by_year_end.values(), key=lambda fact: fact.period_end, reverse=True)


def _is_full_year_from_10k(fact: ReportedFact) -> bool:
    if fact.form not in _ANNUAL_FORMS or fact.period_start is None:
        return False
    days = (fact.period_end - fact.period_start).days
    return _MIN_YEAR_DAYS <= days <= _MAX_YEAR_DAYS
