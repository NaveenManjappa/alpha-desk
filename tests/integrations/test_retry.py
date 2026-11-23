"""Tests for the retry helper. A fake sleep records the waits, so no test actually waits."""

import pytest

from alphadesk.domain.errors import UpstreamError
from alphadesk.integrations.retry import RetryPolicy, call_with_retries, is_retryable_status


class FakeSleep:
    """Records each requested wait instead of waiting."""

    def __init__(self) -> None:
        self.waits: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


class FlakyCall:
    """Raises the given errors in order, then returns "ok". Counts its attempts."""

    def __init__(self, *errors: Exception) -> None:
        self.errors = list(errors)
        self.attempts = 0

    async def __call__(self) -> str:
        self.attempts += 1
        if self.errors:
            raise self.errors.pop(0)
        return "ok"


def _transient() -> UpstreamError:
    return UpstreamError("Provider returned HTTP 503", status_code=503, retryable=True)


def _bad_input() -> UpstreamError:
    return UpstreamError("Provider returned HTTP 400", status_code=400, retryable=False)


POLICY = RetryPolicy(max_attempts=3, base_delay_seconds=0.5, max_delay_seconds=4.0)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_two_failures_then_a_success_takes_exactly_three_attempts() -> None:
    call = FlakyCall(_transient(), _transient())
    sleep = FakeSleep()

    result = await call_with_retries(call, POLICY, sleep=sleep)

    assert result == "ok"
    assert call.attempts == 3
    assert sleep.waits == [0.5, 1.0]  # backoff doubles after each failure


@pytest.mark.unit
@pytest.mark.asyncio
async def test_bad_input_error_is_not_retried() -> None:
    call = FlakyCall(_bad_input())
    sleep = FakeSleep()

    with pytest.raises(UpstreamError) as caught:
        await call_with_retries(call, POLICY, sleep=sleep)

    assert call.attempts == 1
    assert sleep.waits == []
    assert caught.value.status_code == 400


@pytest.mark.unit
@pytest.mark.asyncio
async def test_gives_up_after_max_attempts_and_raises_the_last_error() -> None:
    last = UpstreamError("third", status_code=502, retryable=True)
    call = FlakyCall(_transient(), _transient(), last, _transient())
    sleep = FakeSleep()

    with pytest.raises(UpstreamError) as caught:
        await call_with_retries(call, POLICY, sleep=sleep)

    assert call.attempts == 3
    assert caught.value is last
    assert len(sleep.waits) == 2  # no wait after the final attempt


@pytest.mark.unit
@pytest.mark.asyncio
async def test_other_exceptions_are_never_retried() -> None:
    call = FlakyCall(KeyError("a bug, not an outage"))

    with pytest.raises(KeyError):
        await call_with_retries(call, POLICY, sleep=FakeSleep())

    assert call.attempts == 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_one_attempt_policy_never_retries() -> None:
    call = FlakyCall(_transient())

    with pytest.raises(UpstreamError):
        await call_with_retries(call, RetryPolicy(max_attempts=1), sleep=FakeSleep())

    assert call.attempts == 1


@pytest.mark.unit
def test_backoff_is_capped_at_max_delay() -> None:
    policy = RetryPolicy(max_attempts=6, base_delay_seconds=1.0, max_delay_seconds=3.0)

    assert [policy.delay_after(attempt) for attempt in range(1, 6)] == [1.0, 2.0, 3.0, 3.0, 3.0]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("status", "retryable"),
    [
        (429, True),  # rate limited: wait and it clears
        (500, True),
        (502, True),
        (503, True),
        (504, True),
        (400, False),  # bad request: the same request fails the same way
        (401, False),  # bad key: retrying will not fix it
        (403, False),
        (404, False),
        (422, False),
    ],
)
def test_only_rate_limits_and_server_errors_are_retryable(status: int, retryable: bool) -> None:
    assert is_retryable_status(status) is retryable


@pytest.mark.unit
def test_policy_needs_at_least_one_attempt() -> None:
    with pytest.raises(ValueError, match="max_attempts"):
        RetryPolicy(max_attempts=0)
