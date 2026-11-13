"""Provider-neutral types for company filings data (SEC EDGAR today).

The EDGAR client translates EDGAR's JSON and failures into these types. Services depend
only on them, the same way `market_data.py` keeps the quote service free of Finnhub.
"""

from datetime import date

from pydantic import BaseModel


class ReportedFact(BaseModel):
    """One figure exactly as a company reported it in one filing, before we choose which to use.

    A company reports the same figure many times: last year's revenue appears again as a
    comparison in this year's 10-K. The service picks one; this type keeps them all.

    Attributes:
        concept: The XBRL concept name, e.g. "Revenues" or "NetIncomeLoss".
        unit: The XBRL unit, e.g. "USD" or "USD/shares".
        value: The reported number, in that unit.
        period_start: First day of the period. None for point-in-time figures such as cash.
        period_end: Last day of the period.
        form: The form it was reported in, e.g. "10-K" or "10-Q".
        filed: The date that filing was made.
        filing_url: A link to that filing.
    """

    concept: str
    unit: str
    value: float
    period_start: date | None
    period_end: date
    form: str
    filed: date
    filing_url: str


class Filing(BaseModel):
    """One filing a company made, without its contents.

    Attributes:
        form: The form type, e.g. "10-K", "10-Q" or "8-K".
        filing_date: When it was filed.
        report_date: The period or event it reports on, if the filing gives one.
        url: A link to the filing's main document.
    """

    form: str
    filing_date: date
    report_date: date | None
    url: str


class FilingsDataError(Exception):
    """A filings provider could not answer: timeout, network error, bad status or bad body.

    "No such company" is not this error; clients report that as a missing result.

    Attributes:
        status_code: The HTTP status, if a response arrived. Slice 12 uses it to decide
            which failures are worth retrying.
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
