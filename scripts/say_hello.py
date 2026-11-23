"""Smoke test for Slices 1 and 2: send "Say hello" to the small-tier model and log the reply.

Run with: uv run python scripts/say_hello.py
This makes a real, paid model call. With ALPHADESK_LANGSMITH_TRACING=true it also
produces a trace in LangSmith.
"""

import asyncio
import logging

from langchain_core.tracers.langchain import wait_for_all_tracers

from alphadesk.config.settings import get_settings
from alphadesk.integrations.llm import get_chat_model
from alphadesk.integrations.tracing import configure_tracing

logger = logging.getLogger(__name__)


async def main() -> None:
    """Send one message and log the model's reply."""
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(message)s")
    configure_tracing(settings)  # before the first model call: LangSmith caches its settings

    model = get_chat_model("small", settings)
    reply = await model.ainvoke("Say hello")
    logger.info("Provider: %s", settings.llm_provider)
    logger.info("Reply: %s", reply.text)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    finally:
        # Traces are sent from a background thread. A short script can exit before
        # they are sent, so wait for them. This blocks, so it runs outside the event loop.
        wait_for_all_tracers()
