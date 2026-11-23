"""The `get_quote` tool: a thin wrapper the LLM can call around `QuoteService`.

The docstring of the inner function is a prompt. The model reads its description and
argument docs to decide when to call the tool and what to pass, so it is written for
the model: when to use it, when not to, and what comes back.
"""

from typing import Any

from langchain_core.tools import BaseTool, tool

from alphadesk.services.quotes import QuoteService


def make_get_quote_tool(service: QuoteService) -> BaseTool:
    """Build the `get_quote` tool bound to a service.

    A factory, not a module-level tool, so the service (and its HTTP client) is passed
    in rather than created inside, and tests can pass one backed by a fake client.
    """

    @tool(parse_docstring=True)
    async def get_quote(ticker: str) -> dict[str, Any]:
        """Get the latest share price and today's change for one US-listed company.

        Use it when the question needs a current price or how the stock moved today.
        Do not use it for revenue, earnings or other financial results.
        Returns price, change, quote_time, source_url and as_of. On failure it returns
        error_type and message instead; tell the user what went wrong, do not guess a price.

        Args:
            ticker: The stock ticker symbol, for example "AAPL" for Apple. One ticker only.
        """
        result = await service.get_quote(ticker)
        # A plain dict, so LangChain sends it to the model as JSON.
        return result.model_dump(mode="json")

    return get_quote
