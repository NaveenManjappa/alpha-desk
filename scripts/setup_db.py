"""Create the schemas and tables AlphaDesk needs in Postgres. Safe to run more than once.

Run with: make setup-db     (or: uv run python scripts/setup_db.py)

Needs Postgres running (`docker compose up -d`) and ALPHADESK_POSTGRES_URL set.
"""

import asyncio
import logging

from alphadesk.config.settings import get_settings
from alphadesk.graph.checkpointer import CHECKPOINT_SCHEMA, setup_checkpointer
from alphadesk.repositories.postgres_threads import CONVERSATIONS_SCHEMA, setup_thread_tables

logger = logging.getLogger(__name__)


async def main() -> None:
    """Create the checkpoint and conversation tables, and say where they are."""
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(message)s")
    await setup_checkpointer(settings)
    logger.info("Checkpoint tables are ready in schema '%s'.", CHECKPOINT_SCHEMA)
    await setup_thread_tables(settings)
    logger.info("Conversation list is ready in schema '%s'.", CONVERSATIONS_SCHEMA)


if __name__ == "__main__":
    asyncio.run(main())
