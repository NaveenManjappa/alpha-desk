"""Smoke test for Slice 4: ask the research agent one question and log each step.

Run with: uv run python scripts/ask.py "What is Apple's share price?"
Makes real, paid model calls and may call Finnhub. Needs ALPHADESK_OPENAI_API_KEY and
ALPHADESK_FINNHUB_API_KEY. With ALPHADESK_LANGSMITH_TRACING=true it also produces a trace.
"""

import asyncio
import logging
import sys

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.tracers.langchain import wait_for_all_tracers

from alphadesk.agents.research_agent import create_research_agent
from alphadesk.config.settings import get_settings
from alphadesk.integrations.finnhub import FinnhubClient, create_finnhub_http_client
from alphadesk.integrations.llm import get_chat_model
from alphadesk.integrations.tracing import configure_tracing
from alphadesk.services.quotes import QuoteService

logger = logging.getLogger(__name__)


def _describe(message: BaseMessage) -> str:
    """One line per step, so you can see the loop without opening LangSmith."""
    if isinstance(message, AIMessage) and message.tool_calls:
        calls = ", ".join(f"{call['name']}({call['args']})" for call in message.tool_calls)
        return f"model  -> asks for tool: {calls}"
    if isinstance(message, AIMessage):
        return "model  -> answers (no tool calls, so the loop stops)"
    if isinstance(message, ToolMessage):
        return f"tool   -> {message.name} returned: {message.text}"
    return f"{message.type:<6} -> {message.text}"


async def main(question: str) -> None:
    """Run the agent once and log every message it produced, then the answer."""
    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(message)s")
    configure_tracing(settings)  # before the first model call: LangSmith caches its settings

    async with create_finnhub_http_client(settings) as http:
        agent = create_research_agent(
            model=get_chat_model("small", settings),
            quote_service=QuoteService(FinnhubClient(http)),
        )
        result = await agent.ainvoke({"messages": [{"role": "user", "content": question}]})

    for message in result["messages"]:
        logger.info("%s", _describe(message))
    logger.info("\nAnswer: %s", result["messages"][-1].text)


if __name__ == "__main__":
    try:
        asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "What is Apple's share price?"))
    finally:
        # Traces are sent from a background thread; wait so a short script does not drop them.
        wait_for_all_tracers()
