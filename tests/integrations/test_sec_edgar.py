"""Tests for the SEC EDGAR client. httpx.MockTransport answers in memory, so no network."""

from collections.abc import Callable
from datetime import date

import httpx
import pytest

from alphadesk.config.settings import Settings
from alphadesk.domain.filings import FilingsDataError
from alphadesk.integrations.sec_edgar import EdgarClient, RateLimiter, create_edgar_http_client

Handler = Callable[[httpx.Request], httpx.Response]

TICKERS = {
    "0": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"},
    "1": {"cik_str": 1067983, "ticker": "BRK-B", "title": "BERKSHIRE HATHAWAY INC"},
}

SUBMISSIONS = {
    "cik": "1045810",
    "name": "NVIDIA CORP",
    "filings": {
        "recent": {
            "accessionNumber": ["0001045810-26-000101", "0001045810-26-000090"],
            "filingDate": ["2026-11-01", "2026-08-27"],
            "reportDate": ["", "2026-07-27"],
            "form": ["8-K", "10-Q"],
            "primaryDocument": ["nvda-8k.htm", ""],
            "primaryDocDescription": ["8-K", "10-Q"],
        },
        "files": [],
    },
}

COMPANY_FACTS = {
    "cik": 789019,
    "entityName": "MICROSOFT CORP",
    "facts": {
        "dei": {},
        "us-gaap": {
            "RevenueFromContractWithCustomerExcludingAssessedTax": {
                "label": "Revenue",
                "units": {
                    "USD": [
                        {
                            "start": "2025-07-01",
                            "end": "2026-06-30",
                            "val": 300000000000,
                            "accn": "0000950170-26-000077",
                            "fy": 2026,
                            "fp": "FY",
                            "form": "10-K",
                            "filed": "2026-07-30",
                        }
                    ]
                },
            },
            "AccountsPayableCurrent": {"units": {"USD": []}},
        },
    },
}


def _client(handler: Handler, limiter: RateLimiter | None = None) -> EdgarClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return EdgarClient(http, limiter or RateLimiter(max_per_second=1000))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_cik_loads_the_ticker_file_once_and_maps_share_classes() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=TICKERS)

    client = _client(handler)

    assert await client.get_cik("MSFT") == 789019
    assert await client.get_cik("BRK.B") == 1067983  # EDGAR writes it "BRK-B"
    assert await client.get_cik("ZZZZZ") is None
    assert len(seen) == 1
    assert str(seen[0].url) == "https://www.sec.gov/files/company_tickers.json"


@pytest.mark.unit
def test_urls_use_ten_digit_ciks() -> None:
    client = _client(lambda _: httpx.Response(200))

    assert client.submissions_url(320193) == "https://data.sec.gov/submissions/CIK0000320193.json"
    assert client.company_facts_url(320193) == (
        "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_recent_filings_turns_columns_into_rows_with_links() -> None:
    client = _client(lambda _: httpx.Response(200, json=SUBMISSIONS))

    filings = await client.get_recent_filings(1045810)

    assert filings is not None
    eight_k, ten_q = filings
    assert eight_k.form == "8-K"
    assert eight_k.filing_date == date(2026, 11, 1)
    assert eight_k.report_date is None  # EDGAR's "" becomes None
    assert eight_k.url == (
        "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000101/nvda-8k.htm"
    )
    # No primary document named, so the link falls back to the filing's index page.
    assert ten_q.url == (
        "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000090/"
        "0001045810-26-000090-index.htm"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reported_facts_reads_only_the_concepts_asked_for() -> None:
    client = _client(lambda _: httpx.Response(200, json=COMPANY_FACTS))

    facts = await client.get_reported_facts(
        789019, ["RevenueFromContractWithCustomerExcludingAssessedTax", "NetIncomeLoss"]
    )

    assert facts is not None
    [revenue] = facts
    assert revenue.concept == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert revenue.unit == "USD"
    assert revenue.value == 300_000_000_000
    assert revenue.period_start == date(2025, 7, 1)
    assert revenue.period_end == date(2026, 6, 30)
    assert revenue.form == "10-K"
    assert revenue.filing_url == (
        "https://www.sec.gov/Archives/edgar/data/789019/000095017026000077/"
        "0000950170-26-000077-index.htm"
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_not_found_means_no_data_for_that_company() -> None:
    client = _client(lambda _: httpx.Response(404))

    assert await client.get_reported_facts(1, ["Revenues"]) is None
    assert await client.get_recent_filings(1) is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_error_status_raises_filings_data_error_with_status_code() -> None:
    client = _client(lambda _: httpx.Response(403))

    with pytest.raises(FilingsDataError) as caught:
        await client.get_recent_filings(1045810)

    assert caught.value.status_code == 403


@pytest.mark.unit
@pytest.mark.asyncio
async def test_timeout_raises_filings_data_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    with pytest.raises(FilingsDataError, match="in time"):
        await _client(handler).get_cik("MSFT")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unexpected_body_raises_filings_data_error() -> None:
    client = _client(lambda _: httpx.Response(200, text="<html>maintenance</html>"))

    with pytest.raises(FilingsDataError, match="unexpected shape"):
        await client.get_recent_filings(1045810)
    with pytest.raises(FilingsDataError, match="unexpected shape"):
        await client.get_reported_facts(1045810, ["Revenues"])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_malformed_fact_raises_filings_data_error() -> None:
    bad = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [{"val": "lots"}]}}}}}
    client = _client(lambda _: httpx.Response(200, json=bad))

    with pytest.raises(FilingsDataError, match="unexpected shape"):
        await client.get_reported_facts(1045810, ["Revenues"])


@pytest.mark.unit
@pytest.mark.asyncio
async def test_columns_of_different_lengths_raise_filings_data_error() -> None:
    broken = {"filings": {"recent": {**SUBMISSIONS["filings"]["recent"], "form": ["8-K"]}}}
    client = _client(lambda _: httpx.Response(200, json=broken))

    with pytest.raises(FilingsDataError, match="unexpected shape"):
        await client.get_recent_filings(1045810)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_every_request_waits_for_the_rate_limiter() -> None:
    class CountingLimiter(RateLimiter):
        waits = 0

        async def wait(self) -> None:
            self.waits += 1

    def handler(request: httpx.Request) -> httpx.Response:
        body = SUBMISSIONS if "submissions" in request.url.path else TICKERS
        return httpx.Response(200, json=body)

    limiter = CountingLimiter(max_per_second=1)
    client = _client(handler, limiter)

    await client.get_cik("MSFT")
    await client.get_recent_filings(789019)

    assert limiter.waits == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rate_limiter_spaces_calls_by_the_interval() -> None:
    now = 100.0
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        nonlocal now
        slept.append(seconds)
        now += seconds

    limiter = RateLimiter(max_per_second=5, clock=lambda: now, sleep=fake_sleep)

    await limiter.wait()  # first call goes straight through
    await limiter.wait()  # immediately after: must wait the full 0.2s
    now += 1.0  # a quiet second passes
    await limiter.wait()  # no wait needed

    assert slept == [pytest.approx(0.2)]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_http_client_sends_the_user_agent_sec_requires() -> None:
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        openai_api_key="test-key",  # pyright: ignore[reportArgumentType]
        sec_edgar_user_agent="AlphaDesk tests@example.com",
        sec_edgar_timeout_seconds=3.0,
    )

    async with create_edgar_http_client(settings) as http:
        assert http.headers["User-Agent"] == "AlphaDesk tests@example.com"
        assert http.headers["Accept-Encoding"] == "gzip, deflate"
        assert http.timeout.read == 3.0


@pytest.mark.unit
def test_http_client_requires_a_user_agent() -> None:
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        openai_api_key="test-key",  # pyright: ignore[reportArgumentType]
    )

    with pytest.raises(ValueError, match="ALPHADESK_SEC_EDGAR_USER_AGENT"):
        create_edgar_http_client(settings)
