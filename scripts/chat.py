"""Chat with the research agent on one thread, and inspect what the checkpointer saved.

Run with: uv run python scripts/chat.py            (starts a new thread)
     or:  uv run python scripts/chat.py --thread apple

Type a question, or one of these commands:
  /state         the latest saved state of this thread: every message, and the answer
  /history       every checkpoint of this thread, newest first: one per step
  /new           start a new thread, with no memory
  /thread <id>   switch to another thread, e.g. back to an earlier one
  /quit          exit (Ctrl-D works too)

Memory lives in this process (the in-memory checkpointer), so it is gone when you quit.

Makes real, paid model calls and may call Finnhub and SEC EDGAR. Needs
ALPHADESK_OPENAI_API_KEY, ALPHADESK_FINNHUB_API_KEY and ALPHADESK_SEC_EDGAR_USER_AGENT.
With ALPHADESK_LANGSMITH_TRACING=true it also produces a trace.
"""

import argparse
import asyncio
import logging
from uuid import uuid4

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.tracers.langchain import wait_for_all_tracers
from langgraph.graph.state import CompiledStateGraph

from alphadesk.agents.research_agent import (
    NoAnswerError,
    ask_research_agent,
    create_research_agent,
)
from alphadesk.config.settings import get_settings
from alphadesk.graph.checkpointer import create_checkpointer
from alphadesk.integrations.finnhub import FinnhubClient, create_finnhub_http_client
from alphadesk.integrations.llm import get_chat_model
from alphadesk.integrations.sec_edgar import EdgarClient, RateLimiter, create_edgar_http_client
from alphadesk.integrations.tracing import configure_tracing
from alphadesk.services.filings import FilingsService
from alphadesk.services.financials import FinancialFactsService
from alphadesk.services.quotes import QuoteService

logger = logging.getLogger(__name__)


def _new_thread_id() -> str:
    return uuid4().hex[:8]


def _config(thread_id: str) -> RunnableConfig:
    """The config that points a run, or a state read, at one thread."""
    return {"configurable": {"thread_id": thread_id}}


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


async def _ask(agent: CompiledStateGraph, question: str, thread_id: str) -> None:
    """Ask one question on the thread, log this turn's steps, then the Answer."""
    try:
        run = await ask_research_agent(agent, question, thread_id)
    except NoAnswerError as error:
        logger.warning("No answer: %s", error)
        return
    for message in run.messages:
        logger.info("%s", _describe(message))
    logger.info("\n%s\n", run.answer.model_dump_json(indent=2))


async def _show_state(agent: CompiledStateGraph, thread_id: str) -> None:
    """Log the latest checkpoint of a thread: what the agent will remember next turn.

    `aget_state` returns a `StateSnapshot`. Its `values` are the graph state (here the
    `messages` list and the last `structured_response`). `next` names the nodes still to
    run; it is empty once a run has finished. `config` holds the checkpoint's own ID.
    """
    snapshot = await agent.aget_state(_config(thread_id))
    if not snapshot.values:
        logger.info("Thread %s has no saved state yet.", thread_id)
        return
    messages: list[BaseMessage] = snapshot.values["messages"]
    logger.info(
        "Thread %s, checkpoint %s, step %s, next: %s",
        thread_id,
        snapshot.config.get("configurable", {}).get("checkpoint_id"),
        (snapshot.metadata or {}).get("step"),
        list(snapshot.next) or "nothing (finished)",
    )
    logger.info("%d messages saved:", len(messages))
    for index, message in enumerate(messages):
        logger.info("  %2d. %s", index, _describe(message))
    logger.info("structured_response: %r", snapshot.values.get("structured_response"))


async def _show_history(agent: CompiledStateGraph, thread_id: str) -> None:
    """Log every checkpoint of a thread, newest first: one was saved after each step.

    `source` says what produced the checkpoint: "input" for the question arriving, "loop"
    for a step of the graph (a model or tool node).
    """
    count = 0
    async for snapshot in agent.aget_state_history(_config(thread_id)):
        count += 1
        metadata = snapshot.metadata or {}
        logger.info(
            "step %3s  source %-5s  messages %2d  next %s",
            metadata.get("step"),
            metadata.get("source"),
            len(snapshot.values.get("messages", [])),
            list(snapshot.next),
        )
    if count == 0:
        logger.info("Thread %s has no checkpoints yet.", thread_id)


async def _chat(agent: CompiledStateGraph, thread_id: str) -> None:
    """Read lines until /quit or end of input. Each question continues the current thread."""
    logger.info("Thread %s. Ask a question, or type /state, /history, /new, /quit.", thread_id)
    while True:
        try:
            # input() blocks, so it runs in a worker thread to keep the event loop free.
            line = (await asyncio.to_thread(input, f"[{thread_id}] you> ")).strip()
        except EOFError:
            return
        command, _, argument = line.partition(" ")
        if not line:
            continue
        if command == "/quit":
            return
        if command == "/state":
            await _show_state(agent, thread_id)
        elif command == "/history":
            await _show_history(agent, thread_id)
        elif command == "/new":
            thread_id = _new_thread_id()
            logger.info("New thread %s: no memory of earlier questions.", thread_id)
        elif command == "/thread" and argument:
            thread_id = argument.strip()
            logger.info("Switched to thread %s.", thread_id)
        elif command.startswith("/"):
            logger.info("Unknown command. Try /state, /history, /new, /thread <id>, /quit.")
        else:
            await _ask(agent, line, thread_id)


async def main(thread_id: str) -> None:
    """Build the agent with an in-memory checkpointer and chat on the given thread."""
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
            # One checkpointer for the whole session: every thread's memory lives in it.
            checkpointer=create_checkpointer(),
        )
        await _chat(agent, thread_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chat with the AlphaDesk research agent.")
    parser.add_argument("--thread", default=None, help="Thread ID to use. Default: a new one.")
    args = parser.parse_args()
    try:
        asyncio.run(main(args.thread or _new_thread_id()))
    except KeyboardInterrupt:
        pass
    finally:
        # Traces are sent from a background thread; wait so a short script does not drop them.
        wait_for_all_tracers()
