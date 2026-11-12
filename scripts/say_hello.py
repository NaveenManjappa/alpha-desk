"""Smoke test for Slice 1: send "Say hello" to the small-tier model and log the reply.

Run with: uv run python scripts/say_hello.py
This makes a real, paid model call.
"""

import asyncio
import logging

from alphadesk.config.settings import get_settings
from alphadesk.integrations.llm import get_chat_model

logger = logging.getLogger(__name__)


async def main() -> None:
    """Send one message and log the model's reply."""
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(message)s")

    model = get_chat_model("small", settings)
    reply = await model.ainvoke("Say hello")
    logger.info("Provider: %s", settings.llm_provider)
    logger.info("Reply: %s", reply.text)


if __name__ == "__main__":
    asyncio.run(main())
