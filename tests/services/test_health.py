"""Tests for the health check. Fake Postgres checks: no database."""

import pytest

from alphadesk.domain.health import HealthReport
from alphadesk.services.health import check_health


async def _up() -> bool:
    return True


async def _down() -> bool:
    return False


@pytest.mark.unit
@pytest.mark.asyncio
async def test_reachable_postgres_is_healthy() -> None:
    assert await check_health(_up) == HealthReport(status="ok", postgres="ok")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unreachable_postgres_is_degraded() -> None:
    assert await check_health(_down) == HealthReport(status="degraded", postgres="unreachable")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_postgres_that_is_not_configured_does_not_degrade_health() -> None:
    report = await check_health(None)

    assert report == HealthReport(status="ok", postgres="not_configured")
