"""Provider-neutral market data types (ADR 007).

Any market data client (Finnhub today) translates its provider's responses and failures
into these types. Services depend only on them, so swapping the provider means writing
a new client, not editing the service.
"""

from pydantic import AwareDatetime, BaseModel

from alphadesk.domain.errors import UpstreamError


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


class MarketDataError(UpstreamError):
    """A market data provider could not answer: timeout, network error, bad status or bad body.

    "The symbol does not exist" is not this error; clients report that as a missing quote.
    `status_code` and `retryable` come from `UpstreamError`.
    """
