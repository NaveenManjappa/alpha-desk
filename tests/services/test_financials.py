"""Tests for FinancialFactsService, with a fake filings client. No network, no EDGAR JSON."""

from collections.abc import Sequence
from datetime import date, timedelta

import pytest

from alphadesk.domain.filings import FilingsDataError, ReportedFact
from alphadesk.domain.tool_results import FinancialFactsResult, ToolError
from alphadesk.services.financials import FinancialFactsService


def _fact(
    concept: str,
    value: float,
    start: date | None,
    end: date,
    form: str = "10-K",
    filed: date | None = None,
    unit: str = "USD",
) -> ReportedFact:
    filed = filed or end + timedelta(days=30)
    return ReportedFact(
        concept=concept,
        unit=unit,
        value=value,
        period_start=start,
        period_end=end,
        form=form,
        filed=filed,
        filing_url=f"https://sec.example/{concept}/{end}/{filed}",
    )


def _year(end_year: int) -> tuple[date, date]:
    """A July-to-June fiscal year, like Microsoft's."""
    return date(end_year - 1, 7, 1), date(end_year, 6, 30)


class FakeFactsSource:
    """Knows one ticker and returns canned facts, or raises a canned error."""

    def __init__(
        self,
        facts: list[ReportedFact] | None = None,
        error: Exception | None = None,
        ciks: dict[str, int] | None = None,
    ) -> None:
        self.facts = facts
        self.error = error
        self.ciks = {"MSFT": 789019} if ciks is None else ciks
        self.calls: list[str] = []

    def company_facts_url(self, cik: int) -> str:
        return f"https://filings.example/facts/{cik}"

    async def get_cik(self, ticker: str) -> int | None:
        self.calls.append(ticker)
        return self.ciks.get(ticker)

    async def get_reported_facts(
        self, cik: int, concepts: Sequence[str]
    ) -> list[ReportedFact] | None:
        if self.error is not None:
            raise self.error
        return self.facts


async def _get(facts: list[ReportedFact]) -> FinancialFactsResult:
    result = await FinancialFactsService(FakeFactsSource(facts)).get_financial_facts("MSFT")
    assert isinstance(result, FinancialFactsResult)
    return result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_returns_three_newest_years_of_each_metric_with_sources() -> None:
    facts = [_fact("Revenues", 100.0 + year, *_year(year)) for year in range(2021, 2027)]
    facts.append(_fact("NetIncomeLoss", 40.0, *_year(2026)))
    facts.append(_fact("EarningsPerShareDiluted", 13.5, *_year(2026), unit="USD/shares"))

    result = await _get(facts)

    assert result.ticker == "MSFT"
    assert result.source_url == "https://filings.example/facts/789019"
    revenue = [f for f in result.facts if f.metric == "revenue"]
    assert [f.value for f in revenue] == [2126.0, 2125.0, 2124.0]
    assert revenue[0].period_start == date(2025, 7, 1)
    assert revenue[0].period_end == date(2026, 6, 30)
    assert revenue[0].unit == "USD"
    assert revenue[0].source_url.startswith("https://sec.example/Revenues/2026-06-30")
    [eps] = [f for f in result.facts if f.metric == "eps_diluted"]
    assert eps.value == 13.5
    assert eps.unit == "USD per share"
    assert [f.metric for f in result.facts].count("net_income") == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_ignores_quarters_10qs_and_other_units() -> None:
    start, end = _year(2026)
    facts = [
        _fact("Revenues", 300.0, start, end),
        _fact("Revenues", 80.0, date(2026, 4, 1), end),  # a quarter inside a 10-K
        _fact("Revenues", 999.0, start, end, form="10-Q"),
        _fact("Revenues", 777.0, start, end, unit="EUR"),
    ]

    result = await _get(facts)

    assert [f.value for f in result.facts] == [300.0]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_a_year_reported_twice_uses_the_latest_filing() -> None:
    start, end = _year(2025)
    original = _fact("Revenues", 250.0, start, end, filed=date(2025, 7, 30))
    restated = _fact("Revenues", 245.0, start, end, filed=date(2026, 7, 30))

    result = await _get([original, restated])

    [revenue] = result.facts
    assert revenue.value == 245.0
    assert revenue.source_url == restated.filing_url


@pytest.mark.unit
@pytest.mark.asyncio
async def test_picks_the_concept_with_the_newest_year() -> None:
    # The company used "Revenues" long ago, then switched concept.
    old = _fact("Revenues", 10.0, *_year(2019))
    new = _fact("RevenueFromContractWithCustomerExcludingAssessedTax", 300.0, *_year(2026))

    result = await _get([old, new])

    assert [f.value for f in result.facts] == [300.0]


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("bad_ticker", ["", "123", "MSFT; DROP"])
async def test_bad_input_returns_invalid_input_without_calling_upstream(bad_ticker: str) -> None:
    source = FakeFactsSource([])

    result = await FinancialFactsService(source).get_financial_facts(bad_ticker)

    assert isinstance(result, ToolError)
    assert result.error_type == "invalid_input"
    assert source.calls == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unknown_ticker_returns_not_found() -> None:
    result = await FinancialFactsService(FakeFactsSource([])).get_financial_facts("ZZZZZ")

    assert isinstance(result, ToolError)
    assert result.error_type == "not_found"
    assert "ZZZZZ" in result.message


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("facts", [None, [], [_fact("Revenues", 80.0, *_year(2026), form="10-Q")]])
async def test_no_annual_figures_returns_not_found(facts: list[ReportedFact] | None) -> None:
    result = await FinancialFactsService(FakeFactsSource(facts)).get_financial_facts("MSFT")

    assert isinstance(result, ToolError)
    assert result.error_type == "not_found"
    assert result.source_url == "https://filings.example/facts/789019"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upstream_failure_returns_upstream_error_instead_of_raising() -> None:
    source = FakeFactsSource(error=FilingsDataError("SEC EDGAR returned HTTP 503", 503))

    result = await FinancialFactsService(source).get_financial_facts("MSFT")

    assert isinstance(result, ToolError)
    assert result.error_type == "upstream_error"
    assert "503" not in result.message
