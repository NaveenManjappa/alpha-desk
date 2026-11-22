"""Bounded retries with exponential backoff, for calls to outside data providers.

Only a failure that may clear on its own is retried:

- 429 Too Many Requests: the provider asked us to slow down. Waiting helps.
- 5xx server errors: the provider had a problem. It is often gone a second later.
- Dropped connections: the network blipped. These fail fast, so a retry costs little.

Everything else fails at once. That includes timeouts: a provider slow enough to time out
once is likely to again, and each retry would make the user wait the full timeout again.
A 400 means our request is wrong, a 401 or 403 means the key or User-Agent was refused,
and a body we cannot read will be the same body next time.
Sending any of those again only adds delay and load.

Each client decides whether its own error is retryable (`UpstreamError.retryable`),
because only the client knows whether it timed out, got a status or got a bad body.

Every call here is a read (a GET). A retry can never do anything twice that matters. That
stops being true for calls that change state, such as placing an order in Phase 5. Those
need an idempotency key before they may be retried (ADR 010).
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from alphadesk.config.settings import Settings
from alphadesk.domain.errors import UpstreamError

logger = logging.getLogger(__name__)

_TOO_MANY_REQUESTS = 429
_FIRST_SERVER_ERROR = 500


def is_retryable_status(status_code: int) -> bool:
    """True for an HTTP status that may succeed when the same request is sent again."""
    return status_code == _TOO_MANY_REQUESTS or status_code >= _FIRST_SERVER_ERROR


@dataclass(frozen=True)
class RetryPolicy:
    """How many times to try a call, and how long to wait between tries.

    The wait doubles after each failure, up to `max_delay_seconds`: with the defaults,
    0.5 s, then 1 s. Doubling gives a struggling provider more room each time.

    Attributes:
        max_attempts: Tries in total, the first included. 1 means never retry.
        base_delay_seconds: The wait after the first failure.
        max_delay_seconds: The longest single wait.
    """

    max_attempts: int = 3
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 4.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1.")

    def delay_after(self, attempt: int) -> float:
        """Seconds to wait after failed attempt number `attempt` (counting from 1)."""
        return min(self.base_delay_seconds * 2 ** (attempt - 1), self.max_delay_seconds)


def retry_policy_from_settings(settings: Settings) -> RetryPolicy:
    """The policy every data client uses, from `ALPHADESK_HTTP_*` settings."""
    return RetryPolicy(
        max_attempts=settings.http_max_attempts,
        base_delay_seconds=settings.http_retry_base_delay_seconds,
    )


async def call_with_retries[T](
    call: Callable[[], Awaitable[T]],
    policy: RetryPolicy,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> T:
    """Run `call`, trying again on a retryable `UpstreamError`, up to the policy's limit.

    Args:
        call: Makes one attempt. Called afresh each time, so each attempt is a new request.
        policy: How many attempts, and the waits between them.
        sleep: Waits between attempts. Tests pass a fake so they do not really wait.

    Returns:
        What the first successful attempt returned.

    Raises:
        UpstreamError: The last error, if it was not retryable or no attempts were left.
        Exception: Anything other than an `UpstreamError` is a bug, not an outage, and is
            raised at once.
    """
    attempt = 1
    while True:
        try:
            return await call()
        except UpstreamError as exc:
            if not exc.retryable or attempt >= policy.max_attempts:
                raise
            delay = policy.delay_after(attempt)
            logger.warning(
                "%s (attempt %d of %d). Retrying in %.1fs.",
                exc,
                attempt,
                policy.max_attempts,
                delay,
            )
            await sleep(delay)
            attempt += 1
