"""Wiring: build the services the routes use, once, when the app starts.

This is the app's "composition root", the one place that knows every concrete class and
plugs them together: HTTP clients into integration clients, those into services, services
and the model into the agent, the agent into `ChatService`. Everything else is handed its
dependencies, which is what lets the tests swap any of them for a fake.

The clients and the checkpointer hold open connections, so they are opened in a context
manager that lives as long as the app (see `lifespan` in `api/app.py`) and closed on
shutdown. `open_research_agent` builds just the agent, for the chat script and the evals.
"""

import logging
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
from functools import partial

from fastapi import Request
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph.state import CompiledStateGraph

from alphadesk.agents.research_agent import create_research_agent, stream_research_agent
from alphadesk.config.settings import Settings
from alphadesk.domain.thread import Thread
from alphadesk.graph.checkpointer import open_checkpointer
from alphadesk.graph.threads import read_thread
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
        read_thread: Reads a conversation by its thread ID.
        check_postgres: Pings Postgres, or None when no Postgres URL is set.
    """

    chat: ChatService
    read_thread: Callable[[str], Awaitable[Thread]]
    check_postgres: PostgresCheck | None


@asynccontextmanager
async def open_app_services(settings: Settings) -> AsyncGenerator[AppServices]:
    """Build the real services from settings. Connections are closed on exit.

    Args:
        settings: The app's settings.

    Yields:
        The services, ready for requests.
    """
    async with (
        # One checkpointer for the app: every thread's memory lives in it.
        open_checkpointer(settings) as checkpointer,
        open_research_agent(settings, checkpointer) as agent,
    ):
        yield AppServices(
            # `partial` fills in the agent and its model's price, leaving the
            # (message, thread_id) function that ChatService expects. ChatService never
            # sees the agent itself.
            chat=ChatService(
                partial(stream_research_agent, agent, price=get_model_price("small", settings))
            ),
            read_thread=partial(read_thread, agent),
            check_postgres=(
                partial(postgres_is_reachable, settings) if settings.postgres_url else None
            ),
        )


@asynccontextmanager
async def open_research_agent(
    settings: Settings, checkpointer: BaseCheckpointSaver
) -> AsyncGenerator[CompiledStateGraph]:
    """Build the research agent on real data clients. The clients are closed on exit.

    Shared by the API, `scripts/chat.py` and the evals, so all three run the same agent.
    The checkpointer is passed in because each picks its own: the API and the chat script
    use the configured one, and the evals always use memory.

    Args:
        settings: The app's settings.
        checkpointer: Where the agent saves its threads.

    Yields:
        The agent, ready for `ask_research_agent` or `stream_research_agent`.
    """
    retry = retry_policy_from_settings(settings)
    # An exit stack, because whether the Finnhub client is opened depends on settings.
    # Everything entered on it is closed, in reverse order, when the block ends.
    async with AsyncExitStack() as stack:
        edgar_http = await stack.enter_async_context(create_edgar_http_client(settings))

        # Without a Finnhub key the agent still works: only price questions need it, and
        # the quote tool tells the model prices are unavailable.
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
        yield create_research_agent(
            model=get_chat_model("small", settings),
            quote_service=QuoteService(quote_source),
            financial_facts_service=FinancialFactsService(edgar),
            filings_service=FilingsService(edgar),
            history_max_tokens=settings.history_max_tokens,
            max_model_calls=settings.agent_max_model_calls,
            checkpointer=checkpointer,
        )


def get_services(request: Request) -> AppServices:
    """FastAPI dependency: the services built at startup, kept on `app.state`.

    Tests replace it with `app.dependency_overrides[get_services]`, to hand the routes
    fake services instead.
    """
    return request.app.state.services
