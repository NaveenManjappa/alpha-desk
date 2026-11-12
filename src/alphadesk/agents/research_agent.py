"""The research agent: a model that can call tools in a loop until it can answer.

`create_agent` builds a small LangGraph graph with two nodes, "model" and "tools":

    model --(reply has tool calls)--> tools --> model --(no tool calls)--> end

This module decides what goes into that loop: which prompt and which tools. It does not
choose the model or create the tool's dependencies; the caller passes them in.
"""

from importlib.resources import files

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langgraph.graph.state import CompiledStateGraph

from alphadesk.services.quotes import QuoteService
from alphadesk.tools.quote_tool import make_get_quote_tool

_PROMPT_FILE = "research_agent.md"


def load_system_prompt() -> str:
    """Read the research agent's system prompt from `prompts/`.

    `importlib.resources` finds the file inside the installed package, so this works
    from any working directory, not only the repo root.
    """
    return files("alphadesk").joinpath("prompts", _PROMPT_FILE).read_text(encoding="utf-8")


def create_research_agent(model: BaseChatModel, quote_service: QuoteService) -> CompiledStateGraph:
    """Build the research agent.

    Args:
        model: The chat model, from `get_chat_model`. Passed in so tests can use a fake.
        quote_service: Backs the `get_quote` tool. Passed in so tests can use a fake client.

    Returns:
        A compiled graph. Run it with
        `await agent.ainvoke({"messages": [{"role": "user", "content": question}]})`.
        The result's "messages" list holds every step: the question, each model reply,
        each tool result, and the final answer last.
    """
    return create_agent(
        model=model,
        tools=[make_get_quote_tool(quote_service)],
        system_prompt=load_system_prompt(),
        name="research_agent",
    )
