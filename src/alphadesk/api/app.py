"""The FastAPI application.

Start it with `make run`, which runs:

    uvicorn alphadesk.api.app:create_app --factory

`--factory` tells uvicorn to call `create_app()` to get the app, rather than importing a
ready-made one, so nothing is built at import time.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from langchain_core.tracers.langchain import wait_for_all_tracers

from alphadesk.api.dependencies import open_app_services
from alphadesk.api.routes import router
from alphadesk.config.settings import get_settings
from alphadesk.integrations.tracing import configure_tracing

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Build the app. Its services are opened at startup, by `lifespan`."""
    app = FastAPI(title="AlphaDesk", lifespan=lifespan)
    app.include_router(router)
    return app


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Run once around the app's whole life: startup before `yield`, shutdown after it.

    Services are opened here, not per request, so HTTP clients and the database
    connection are reused. The routes find them on `app.state` (see `get_services`).
    """
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(levelname)s %(name)s: %(message)s")
    configure_tracing(settings)  # before the first model call: LangSmith caches its settings
    try:
        async with open_app_services(settings) as services:
            app.state.services = services
            logger.info("AlphaDesk API ready. Checkpointer: %s.", settings.checkpointer)
            yield
    finally:
        # Traces are sent from a background thread. Waiting for them blocks, so it runs in
        # a worker thread to keep the event loop free.
        await asyncio.to_thread(wait_for_all_tracers)
