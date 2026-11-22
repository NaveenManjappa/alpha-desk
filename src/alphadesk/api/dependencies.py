"""Wiring: build the services the routes use, once, when the app starts.

This is the app's "composition root", the one place that knows every concrete class and
plugs them together: HTTP clients into integration clients, those into services, services
and the model into the agent, the agent into `ChatService`. Everything else is handed its
dependencies, which is what lets the tests swap any of them for a fake.

The clients and the checkpointer hold open connections, so they are opened in a context
manager that lives as long as the app (see `lifespan` in `api/app.py`) and closed on
shutdown.
"""

import logging
from collections.abc import AsyncGenerator
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from functools import partial

from fastapi import Request

from alphadesk.agents.research_agent import create_research_agent, stream_research_agent
from alphadesk.config.settings import Settings
from alphadesk.graph.checkpointer import open_checkpointer
from alphadesk.integrations.finnhub import FinnhubClient, create_finnhub_http_client
from alphadesk.integrations.llm import get_chat_model, get_model_price
from alphadesk.integrations.postgres import postgres_is_reachable
from alphadesk.integrations.retry import retry_policy_from_settings
from alphadesk.integrations.sec_edgar import EdgarClient, RateLimiter, create_edgar_http_client
from alphadesk.services.chat import ChatService
from alphadesk.services.filings import FilingsService
from alphadesk.services.financials import FinancialFactsService
from alphadesk.services.health import PostgresCheck
from alphadesk.services.quotes import QuoteService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AppServices:
    """Everything the routes need, built once at startup.

    Attributes:
        chat: Runs chat turns.
        check_postgres: Pings Postgres, or None when no Postgres URL is set.
    """

    chat: ChatService
    check_postgres: PostgresCheck | None


@asynccontextmanager
async def open_app_services(settings: Settings) -> AsyncGenerator[AppServices]:
    """Build the real services from settings. Connections are closed on exit.

    Args:
        settings: The app's settings.

    Yields:
        The services, ready for requests.
    """
    retry = retry_policy_from_settings(settings)
    # An exit stack, because whether the Finnhub client is opened depends on settings.
    # Everything entered on it is closed, in reverse order, when the block ends.
    async with AsyncExitStack() as stack:
        edgar_http = await stack.enter_async_context(create_edgar_http_client(settings))
        # One checkpointer for the app: every thread's memory lives in it.
        checkpointer = await stack.enter_async_context(open_checkpointer(settings))

        # Without a Finnhub key the API still starts: only price questions need it, and the
        # quote tool tells the model prices are unavailable.
        quote_source: FinnhubClient | None = None
        if settings.finnhub_api_key:
            finnhub_http = await stack.enter_async_context(create_finnhub_http_client(settings))
            quote_source = FinnhubClient(finnhub_http, retry)
        else:
            logger.warning(
                "ALPHADESK_FINNHUB_API_KEY is not set. Price questions will say prices are "
                "unavailable."
            )

        # One EDGAR client (and so one rate limiter) shared by both EDGAR tools.
        edgar = EdgarClient(
            edgar_http, RateLimiter(settings.sec_edgar_max_requests_per_second), retry
        )
        agent = create_research_agent(
            model=get_chat_model("small", settings),
            quote_service=QuoteService(quote_source),
            financial_facts_service=FinancialFactsService(edgar),
            filings_service=FilingsService(edgar),
            history_max_tokens=settings.history_max_tokens,
            max_model_calls=settings.agent_max_model_calls,
            checkpointer=checkpointer,
        )
        yield AppServices(
            # `partial` fills in the agent and its model's price, leaving the
            # (message, thread_id) function that ChatService expects. ChatService never
            # sees the agent itself.
            chat=ChatService(
                partial(stream_research_agent, agent, price=get_model_price("small", settings))
            ),
            check_postgres=(
                partial(postgres_is_reachable, settings) if settings.postgres_url else None
            ),
        )


def get_services(request: Request) -> AppServices:
    """FastAPI dependency: the services built at startup, kept on `app.state`.

    Tests replace it with `app.dependency_overrides[get_services]`, to hand the routes
    fake services instead.
    """
    return request.app.state.services
