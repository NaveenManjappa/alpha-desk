"""Smoke test: ask the research agent one question, log each step, then print the Answer.

Run with: uv run python scripts/ask.py "What is Apple's share price?"
Makes real, paid model calls and may call Finnhub and SEC EDGAR. Needs
ALPHADESK_OPENAI_API_KEY, ALPHADESK_FINNHUB_API_KEY and ALPHADESK_SEC_EDGAR_USER_AGENT.
With ALPHADESK_LANGSMITH_TRACING=true it also produces a trace.
"""

import asyncio
import logging
import sys

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.tracers.langchain import wait_for_all_tracers

from alphadesk.agents.research_agent import answer_from_agent_state, create_research_agent
from alphadesk.config.settings import get_settings
from alphadesk.integrations.finnhub import FinnhubClient, create_finnhub_http_client
from alphadesk.integrations.llm import get_chat_model
from alphadesk.integrations.sec_edgar import EdgarClient, RateLimiter, create_edgar_http_client
from alphadesk.integrations.tracing import configure_tracing
from alphadesk.services.filings import FilingsService
from alphadesk.services.financials import FinancialFactsService
from alphadesk.services.quotes import QuoteService

logger = logging.getLogger(__name__)


def _describe(message: BaseMessage) -> str:
    """One line per step, so you can see the loop without opening LangSmith."""
    if isinstance(message, AIMessage) and message.tool_calls:
        calls = ", ".join(f"{call['name']}({call['args']})" for call in message.tool_calls)
        return f"model  -> calls tool: {calls}"
    if isinstance(message, AIMessage):
        return f"model  -> replies without a tool call: {message.text}"
    if isinstance(message, ToolMessage):
        return f"tool   -> {message.name} returned: {message.text}"
    return f"{message.type:<6} -> {message.text}"


async def main(question: str) -> None:
    """Run the agent once, log every message it produced, then print the typed Answer."""
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(message)s")
    configure_tracing(settings)  # before the first model call: LangSmith caches its settings

    async with (
        create_finnhub_http_client(settings) as finnhub_http,
        create_edgar_http_client(settings) as edgar_http,
    ):
        # One EDGAR client (and so one rate limiter) shared by both EDGAR tools.
        edgar = EdgarClient(edgar_http, RateLimiter(settings.sec_edgar_max_requests_per_second))
        agent = create_research_agent(
            model=get_chat_model("small", settings),
            quote_service=QuoteService(FinnhubClient(finnhub_http)),
            financial_facts_service=FinancialFactsService(edgar),
            filings_service=FilingsService(edgar),
        )
        result = await agent.ainvoke({"messages": [{"role": "user", "content": question}]})

    for message in result["messages"]:
        logger.info("%s", _describe(message))
    answer = answer_from_agent_state(result)
    logger.info("\n%r", answer)
    logger.info("\n%s", answer.model_dump_json(indent=2))


if __name__ == "__main__":
    try:
        asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "What is Apple's share price?"))
    finally:
        # Traces are sent from a background thread; wait so a short script does not drop them.
        wait_for_all_tracers()
