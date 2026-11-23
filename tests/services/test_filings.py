"""Tests for FilingsService, with a fake filings client. No network, no EDGAR JSON."""

from datetime import date, timedelta

import pytest

from alphadesk.domain.filings import Filing, FilingsDataError
from alphadesk.domain.tool_results import RecentFilingsResult, ToolError
from alphadesk.services.filings import FilingsService


def _filing(form: str, filed: date) -> Filing:
    return Filing(form=form, filing_date=filed, report_date=None, url=f"https://sec.example/{form}")


class FakeFilingsSource:
    """Knows one ticker and returns canned filings, or raises a canned error."""

    def __init__(self, filings: list[Filing] | None = None, error: Exception | None = None):
        self.filings = filings
        self.error = error
        self.calls: list[str] = []

    def submissions_url(self, cik: int) -> str:
        return f"https://filings.example/submissions/{cik}"

    async def get_cik(self, ticker: str) -> int | None:
        self.calls.append(ticker)
        return 1045810 if ticker == "NVDA" else None

    async def get_recent_filings(self, cik: int) -> list[Filing] | None:
        if self.error is not None:
            raise self.error
        return self.filings


@pytest.mark.unit
@pytest.mark.asyncio
async def test_keeps_latest_10k_latest_10q_and_five_8ks_newest_first() -> None:
    day = date(2026, 11, 1)
    filings = [_filing("8-K", day - timedelta(days=i)) for i in range(8)]
    filings += [
        _filing("10-Q", date(2026, 8, 27)),
        _filing("10-Q", date(2026, 5, 28)),
        _filing("10-K", date(2026, 2, 26)),
        _filing("10-K", date(2025, 2, 26)),
        _filing("4", date(2026, 11, 2)),  # insider trade: not wanted
        _filing("10-K/A", date(2026, 3, 1)),  # amendment: not wanted
    ]

    result = await FilingsService(FakeFilingsSource(filings)).list_recent_filings("nvda")

    assert isinstance(result, RecentFilingsResult)
    assert result.ticker == "NVDA"
    assert result.source_url == "https://filings.example/submissions/1045810"
    assert [f.form for f in result.filings] == ["8-K"] * 5 + ["10-Q", "10-K"]
    assert result.filings[0].filing_date == day
    assert result.filings[-2].filing_date == date(2026, 8, 27)
    assert result.filings[-1].filing_date == date(2026, 2, 26)


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("bad_ticker", ["", "123", "NVDA; DROP"])
async def test_bad_input_returns_invalid_input_without_calling_upstream(bad_ticker: str) -> None:
    source = FakeFilingsSource([])

    result = await FilingsService(source).list_recent_filings(bad_ticker)

    assert isinstance(result, ToolError)
    assert result.error_type == "invalid_input"
    assert source.calls == []


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unknown_ticker_returns_not_found() -> None:
    result = await FilingsService(FakeFilingsSource([])).list_recent_filings("ZZZZZ")

    assert isinstance(result, ToolError)
    assert result.error_type == "not_found"


@pytest.mark.unit
@pytest.mark.asyncio
@pytest.mark.parametrize("filings", [None, [], [_filing("4", date(2026, 11, 2))]])
async def test_no_key_filings_returns_not_found(filings: list[Filing] | None) -> None:
    result = await FilingsService(FakeFilingsSource(filings)).list_recent_filings("NVDA")

    assert isinstance(result, ToolError)
    assert result.error_type == "not_found"
    assert result.source_url == "https://filings.example/submissions/1045810"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upstream_failure_returns_upstream_error_instead_of_raising() -> None:
    source = FakeFilingsSource(error=FilingsDataError("SEC EDGAR returned HTTP 503", 503))

    result = await FilingsService(source).list_recent_filings("NVDA")

    assert isinstance(result, ToolError)
    assert result.error_type == "upstream_error"
    assert result.source_url == "https://filings.example/submissions/1045810"
    assert "503" not in result.message
