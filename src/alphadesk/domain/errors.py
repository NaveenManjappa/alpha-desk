"""Errors shared across the app that are not tied to one provider or one layer.

Defined in `domain/` so that `services/` can catch them without importing a client, a
framework or LangChain.
"""


class UpstreamError(Exception):
    """An outside data provider could not answer: timeout, network error, bad status or body.

    Each provider's client raises its own subclass (`MarketDataError`, `FilingsDataError`),
    so services can tell which provider failed. The retry helper only needs this base.

    Attributes:
        status_code: The HTTP status, if a response arrived.
        retryable: True if the same request may succeed when sent again: a rate limit, a
            server error or a dropped connection. False for anything that
            would fail the same way again, such as a bad request, a rejected key or a
            body we cannot read. The client sets it, because only the client knows
            what went wrong.
    """

    def __init__(
        self, message: str, status_code: int | None = None, retryable: bool = False
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class RunLimitError(Exception):
    """The agent reached its limit of model calls for one run before it could answer.

    The limit protects against a model that keeps calling tools and never answers, which
    would otherwise spend tokens without end.
    """
