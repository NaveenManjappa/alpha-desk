"""Switch LangSmith tracing on or off from our settings (ADR 008).

LangChain traces itself: every model, tool and agent call is recorded automatically
when LangSmith's environment variables are set. So we write no tracing code. This
module only copies our settings into the variable names LangSmith reads.

Why copy at all? Our settings come from `ALPHADESK_*` variables and `.env`, but
pydantic-settings does not put `.env` values into `os.environ`, and LangSmith reads
only `os.environ`. LangSmith also caches what it reads, so call `configure_tracing`
once at startup, before the first model call.
"""

import logging
import os
from collections.abc import MutableMapping

from alphadesk.config.settings import Settings

logger = logging.getLogger(__name__)


def configure_tracing(settings: Settings, environ: MutableMapping[str, str] = os.environ) -> None:
    """Set the LangSmith environment variables from settings.

    Tracing is always set explicitly to "true" or "false", so our settings decide,
    not whatever happens to be in the shell.

    Args:
        settings: Application settings.
        environ: Where to write the variables. The real environment by default;
            tests pass a plain dict.
    """
    if not settings.langsmith_tracing:
        environ["LANGSMITH_TRACING"] = "false"
        logger.info("LangSmith tracing is off")
        return

    # The settings validator guarantees the key exists when tracing is on.
    assert settings.langsmith_api_key is not None
    environ["LANGSMITH_TRACING"] = "true"
    environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key.get_secret_value()
    environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    if settings.langsmith_endpoint:
        environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
    logger.info("LangSmith tracing is on, project: %s", settings.langsmith_project)
