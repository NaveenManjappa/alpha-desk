"""A small async client for SEC EDGAR's free JSON APIs.

This module is the only place that knows EDGAR: its URLs, JSON shapes and fair-access
rules. SEC's developer guidance (sec.gov/os/accessing-edgar-data) asks every caller to:

- declare a User-Agent that names them and gives a contact email, and
- send no more than 10 requests per second in total.

`create_edgar_http_client` sets the header; `RateLimiter` keeps us under the limit.
The client reads only JSON metadata. It never downloads filing documents; it only
builds links to them.
"""

import asyncio
import json
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from datetime import date

import httpx
from pydantic import BaseModel, Field, TypeAdapter, ValidationError, field_validator

from alphadesk.config.settings import Settings
from alphadesk.domain.filings import Filing, FilingsDataError, ReportedFact

logger = logging.getLogger(__name__)

# SEC's fixed public addresses. Ticker map on www.sec.gov; JSON APIs on data.sec.gov.
_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_DATA_URL = "https://data.sec.gov"
_ARCHIVES_URL = "https://www.sec.gov/Archives/edgar/data"


class RateLimiter:
    """Spaces calls at least `1 / max_per_second` seconds apart, across concurrent callers.

    The lock makes callers queue: each one waits for the previous caller's slot to pass.
    The clock and sleep functions are passed in so tests can check the timing without waiting.
    """

    def __init__(
        self,
        max_per_second: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._interval = 1.0 / max_per_second
        self._clock = clock
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._next_allowed: float | None = None

    async def wait(self) -> None:
        """Return when it is this caller's turn to send a request."""
        async with self._lock:
            now = self._clock()
            if self._next_allowed is not None and now < self._next_allowed:
                await self._sleep(self._next_allowed - now)
                now = self._next_allowed
            self._next_allowed = now + self._interval


# --- EDGAR's raw JSON, with readable names. Private to this module. ---


class _TickerEntry(BaseModel):
    """One row of `company_tickers.json`: {"cik_str": 320193, "ticker": "AAPL", "title": ...}."""

    cik: int = Field(alias="cik_str")
    ticker: str


# The file is an object keyed "0", "1", ... rather than a list.
_TICKER_FILE = TypeAdapter(dict[str, _TickerEntry])


class _RecentFilings(BaseModel):
    """`filings.recent` in a submissions file. EDGAR stores it as columns: one list per
    field, where position i in every list describes the same filing."""

    accession_number: list[str] = Field(alias="accessionNumber")
    filing_date: list[date] = Field(alias="filingDate")
    report_date: list[date | None] = Field(alias="reportDate")
    form: list[str]
    primary_document: list[str] = Field(alias="primaryDocument")

    @field_validator("report_date", mode="before")
    @classmethod
    def _blank_means_none(cls, values: list[str]) -> list[str | None]:
        """EDGAR writes "" when a filing has no report date."""
        return [value or None for value in values]


class _FilingsSection(BaseModel):
    recent: _RecentFilings


class _Submissions(BaseModel):
    """The parts of `/submissions/CIK##########.json` we use."""

    filings: _FilingsSection


class _Fact(BaseModel):
    """One reported value of a concept, from `/api/xbrl/companyfacts/`."""

    start: date | None = None  # absent for point-in-time values
    end: date
    val: float
    accn: str  # accession number of the filing that reported it
    form: str
    filed: date


class _Concept(BaseModel):
    """One XBRL concept: its values grouped by unit, e.g. {"USD": [...]}."""

    units: dict[str, list[_Fact]]


def create_edgar_http_client(settings: Settings) -> httpx.AsyncClient:
    """Build the HTTP client for SEC EDGAR, with the User-Agent SEC requires and a timeout.

    Use it as a context manager so the connection pool is closed:
    `async with create_edgar_http_client(settings) as http: ...`

    Raises:
        ValueError: If ALPHADESK_SEC_EDGAR_USER_AGENT is not set.
    """
    if settings.sec_edgar_user_agent is None:
        raise ValueError(
            "ALPHADESK_SEC_EDGAR_USER_AGENT is missing. SEC requires a name and contact "
            "email, e.g. 'AlphaDesk you@example.com'. Set it in the environment or .env."
        )
    return httpx.AsyncClient(
        timeout=settings.sec_edgar_timeout_seconds,
        # Both headers are from SEC's guidance. httpx sets Host itself from each URL.
        headers={
            "User-Agent": settings.sec_edgar_user_agent,
            "Accept-Encoding": "gzip, deflate",
        },
    )


class EdgarClient:
    """Calls SEC EDGAR's JSON APIs and returns provider-neutral results."""

    def __init__(self, http: httpx.AsyncClient, rate_limiter: RateLimiter) -> None:
        """Args:
        http: Built by `create_edgar_http_client`, or a fake in tests.
        rate_limiter: Shared by every request this client sends.
        """
        self._http = http
        self._rate_limiter = rate_limiter
        self._ciks: dict[str, int] | None = None  # ticker -> CIK, loaded on first use

    def submissions_url(self, cik: int) -> str:
        """Where a company's filing list comes from. EDGAR wants the CIK as 10 digits."""
        return f"{_DATA_URL}/submissions/CIK{cik:010d}.json"

    def company_facts_url(self, cik: int) -> str:
        """Where a company's reported financial figures come from."""
        return f"{_DATA_URL}/api/xbrl/companyfacts/CIK{cik:010d}.json"

    async def get_cik(self, ticker: str) -> int | None:
        """Look up the Central Index Key (CIK), EDGAR's own ID for a company.

        The ticker file is downloaded once per client, not once per question.

        Args:
            ticker: An upper-case ticker, e.g. "AAPL" or "BRK.B".

        Returns:
            The CIK, or None if EDGAR does not know the ticker.

        Raises:
            FilingsDataError: If the ticker file could not be fetched or read.
        """
        if self._ciks is None:
            self._ciks = await self._load_ciks()
        # EDGAR writes share classes with a dash ("BRK-B") where many sites use a dot.
        return self._ciks.get(ticker.replace(".", "-"))

    async def get_recent_filings(self, cik: int) -> list[Filing] | None:
        """A company's recent filings of every form, newest first, as EDGAR lists them.

        Returns:
            The filings, or None if EDGAR has no record for this CIK.

        Raises:
            FilingsDataError: On timeout, network failure, a bad status or an unexpected body.
        """
        body = await self._get(self.submissions_url(cik))
        if body is None:
            return None
        try:
            recent = _Submissions.model_validate_json(body).filings.recent
            rows = zip(
                recent.form,
                recent.filing_date,
                recent.report_date,
                recent.accession_number,
                recent.primary_document,
                strict=True,  # the columns must line up; a mismatch means a bad body
            )
            return [
                Filing(
                    form=form,
                    filing_date=filed,
                    report_date=reported,
                    url=self._document_url(cik, accession, document),
                )
                for form, filed, reported, accession, document in rows
            ]
        except (ValidationError, ValueError) as exc:
            raise FilingsDataError("SEC EDGAR sent filings in an unexpected shape") from exc

    async def get_reported_facts(
        self, cik: int, concepts: Sequence[str]
    ) -> list[ReportedFact] | None:
        """Every value a company reported for the given US-GAAP concepts, in every filing.

        The full company facts file holds thousands of concepts; only those asked for are read.

        Args:
            cik: The company's CIK.
            concepts: US-GAAP concept names, e.g. ["Revenues", "NetIncomeLoss"].

        Returns:
            The facts (empty if none of the concepts were reported), or None if EDGAR has
            no financial data for this company.

        Raises:
            FilingsDataError: On timeout, network failure, a bad status or an unexpected body.
        """
        body = await self._get(self.company_facts_url(cik))
        if body is None:
            return None
        try:
            us_gaap = json.loads(body).get("facts", {}).get("us-gaap", {})
            facts: list[ReportedFact] = []
            for concept in concepts:
                if concept not in us_gaap:
                    continue
                for unit, values in _Concept.model_validate(us_gaap[concept]).units.items():
                    facts.extend(self._to_reported_fact(cik, concept, unit, v) for v in values)
            return facts
        except (ValidationError, ValueError, AttributeError) as exc:
            # ValueError covers bad JSON; AttributeError a section that is not an object.
            raise FilingsDataError("SEC EDGAR sent financial data in an unexpected shape") from exc

    async def _load_ciks(self) -> dict[str, int]:
        body = await self._get(_TICKERS_URL)
        if body is None:
            raise FilingsDataError("SEC EDGAR's ticker file was not found", status_code=404)
        try:
            entries = _TICKER_FILE.validate_json(body).values()
        except ValidationError as exc:
            raise FilingsDataError("SEC EDGAR's ticker file has an unexpected shape") from exc
        return {entry.ticker.upper(): entry.cik for entry in entries}

    def _to_reported_fact(self, cik: int, concept: str, unit: str, fact: _Fact) -> ReportedFact:
        return ReportedFact(
            concept=concept,
            unit=unit,
            value=fact.val,
            period_start=fact.start,
            period_end=fact.end,
            form=fact.form,
            filed=fact.filed,
            filing_url=self._index_url(cik, fact.accn),
        )

    def _index_url(self, cik: int, accession: str) -> str:
        """The filing's index page, which lists and links all its documents."""
        return f"{_ARCHIVES_URL}/{cik}/{accession.replace('-', '')}/{accession}-index.htm"

    def _document_url(self, cik: int, accession: str, document: str) -> str:
        """The filing's main document, or its index page if EDGAR names no main document."""
        if not document:
            return self._index_url(cik, accession)
        return f"{_ARCHIVES_URL}/{cik}/{accession.replace('-', '')}/{document}"

    async def _get(self, url: str) -> bytes | None:
        """GET a URL within SEC's rate limit. Returns None on 404.

        Raises:
            FilingsDataError: On timeout, network failure or any other non-2xx status.
        """
        await self._rate_limiter.wait()
        try:
            response = await self._http.get(url)
            if response.status_code == httpx.codes.NOT_FOUND:
                return None
            response.raise_for_status()
            return response.content
        except httpx.TimeoutException as exc:
            raise FilingsDataError("SEC EDGAR did not answer in time") from exc
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            logger.warning("SEC EDGAR returned HTTP %s for %s", status, url)
            raise FilingsDataError(f"SEC EDGAR returned HTTP {status}", status_code=status) from exc
        except httpx.RequestError as exc:
            raise FilingsDataError(f"Could not reach SEC EDGAR: {type(exc).__name__}") from exc
