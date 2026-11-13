"""The `list_recent_filings` tool: a thin wrapper the LLM can call around `FilingsService`.

As with `get_quote`, the docstring is a prompt written for the model.
"""

from typing import Any

from langchain_core.tools import BaseTool, tool

from alphadesk.services.filings import FilingsService


def make_list_recent_filings_tool(service: FilingsService) -> BaseTool:
    """Build the `list_recent_filings` tool bound to a service."""

    @tool(parse_docstring=True)
    async def list_recent_filings(ticker: str) -> dict[str, Any]:
        """List a US-listed company's latest SEC filings, with dates and links.

        Use it when asked what a company has filed, or for links to its annual or quarterly
        reports. Returns, newest first, its latest 10-K (annual report), latest 10-Q
        (quarterly report) and up to five latest 8-Ks (event notices). Each has form,
        filing_date, report_date and url. It does not read what the filings say, and it
        gives no financial figures: use get_financial_facts for those.
        On failure it returns error_type and message instead; tell the user, do not guess.

        Args:
            ticker: The stock ticker symbol, for example "NVDA" for Nvidia. One ticker only.
        """
        result = await service.list_recent_filings(ticker)
        return result.model_dump(mode="json")

    return list_recent_filings
