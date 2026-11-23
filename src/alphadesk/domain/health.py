"""The health report `GET /health` returns.

The TypeScript models in `web/` mirror `HealthReport`; change both together.
"""

from typing import Literal

from pydantic import BaseModel

# "not_configured": no Postgres URL is set, so there is nothing to check.
CheckResult = Literal["ok", "unreachable", "not_configured"]


class HealthReport(BaseModel):
    """Whether the API is running, and whether the services it depends on answer.

    Attributes:
        status: "ok" if every configured dependency answered, otherwise "degraded".
        postgres: The result of the Postgres check.
    """

    status: Literal["ok", "degraded"]
    postgres: CheckResult
