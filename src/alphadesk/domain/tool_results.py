"""What tools hand back to the model: a typed result on success, a typed error on failure.

Tools never raise into the agent loop. A failure becomes a `ToolError` the model can read,
so it can tell the user what went wrong instead of the whole run crashing.
"""

from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel

ToolErrorType = Literal["invalid_input", "not_found", "upstream_error"]


class ToolError(BaseModel):
    """A failed tool call, returned as data.

    Attributes:
        error_type: "invalid_input" means fix the arguments; "not_found" means the
            input was well formed but no such thing exists; "upstream_error" means the
            data provider failed, and trying again later may work.
        message: A plain sentence for the model, written by us, never copied from upstream.
        source_url: The address that was called, if the call got that far.
        as_of: When the failure happened (UTC).
    """

    error_type: ToolErrorType
    message: str
    source_url: str | None = None
    as_of: AwareDatetime


class QuoteResult(BaseModel):
    """The latest share price for one ticker.

    Attributes:
        ticker: The normalised symbol, e.g. "AAPL".
        price: Latest traded price in US dollars.
        change: Change in US dollars since the previous close.
        quote_time: When the provider says this price was set (UTC). On a free plan it
            may be delayed, so it is shown to the user.
        source_url: Where the data came from. Never contains an API key.
        as_of: When we fetched it (UTC).
    """

    ticker: str
    price: float
    change: float
    quote_time: datetime
    source_url: str
    as_of: AwareDatetime
