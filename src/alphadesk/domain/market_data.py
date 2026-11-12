"""Provider-neutral market data types (ADR 007).

Any market data client (Finnhub today) translates its provider's responses and failures
into these types. Services depend only on them, so swapping the provider means writing
a new client, not editing the service.
"""

from pydantic import AwareDatetime, BaseModel


class MarketQuote(BaseModel):
    """A provider's latest quote for one symbol, already in our units.

    Attributes:
        price: Latest traded price in US dollars.
        change: Change in US dollars since the previous close.
        quote_time: When the provider says this price was set (UTC).
    """

    price: float
    change: float
    quote_time: AwareDatetime


class MarketDataError(Exception):
    """A market data provider could not answer: timeout, network error, bad status or bad body.

    "The symbol does not exist" is not this error; clients report that as a missing quote.

    Attributes:
        status_code: The HTTP status, if a response arrived. Slice 12 uses it to decide
            which failures are worth retrying.
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
