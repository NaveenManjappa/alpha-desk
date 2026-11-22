"""The health check: is the API running, and can it reach what it depends on?

Only Postgres is checked for now: it holds every conversation when the checkpointer is
"postgres". Qdrant and Redis join the check when later phases start using them.
"""

from collections.abc import Awaitable, Callable

from alphadesk.domain.health import CheckResult, HealthReport

# Returns True if Postgres answered. From `integrations.postgres.postgres_is_reachable`.
PostgresCheck = Callable[[], Awaitable[bool]]


async def check_health(check_postgres: PostgresCheck | None) -> HealthReport:
    """Run every dependency check and sum them up.

    Args:
        check_postgres: Pings Postgres, or None when no Postgres URL is configured. A
            dependency that is not configured cannot be down, so it does not make the
            report degraded.

    Returns:
        The report. `status` is "degraded" if any configured dependency did not answer.
    """
    postgres: CheckResult
    if check_postgres is None:
        postgres = "not_configured"
    elif await check_postgres():
        postgres = "ok"
    else:
        postgres = "unreachable"
    status = "degraded" if postgres == "unreachable" else "ok"
    return HealthReport(status=status, postgres=postgres)
