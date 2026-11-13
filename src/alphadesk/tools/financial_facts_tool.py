"""The `get_financial_facts` tool: a thin wrapper the LLM can call around `FinancialFactsService`.

As with `get_quote`, the docstring is a prompt written for the model.
"""

from typing import Any

from langchain_core.tools import BaseTool, tool

from alphadesk.services.financials import FinancialFactsService


def make_get_financial_facts_tool(service: FinancialFactsService) -> BaseTool:
    """Build the `get_financial_facts` tool bound to a service."""

    @tool(parse_docstring=True)
    async def get_financial_facts(ticker: str) -> dict[str, Any]:
        """Get revenue, net income and diluted EPS for a company's last three fiscal years.

        Figures are annual, from the US-listed company's SEC 10-K filings. Use it for
        questions about revenue, sales, profit, earnings or EPS, or how they changed over
        the years. Do not use it for the share price, or to list filings.
        Returns a list of facts, each with metric, value, unit, period_start, period_end and
        source_url (the 10-K it came from). "Last year" means the fact with the latest
        period_end; companies' fiscal years often do not end in December.
        On failure it returns error_type and message instead; tell the user, do not guess.

        Args:
            ticker: The stock ticker symbol, for example "MSFT" for Microsoft. One ticker only.
        """
        result = await service.get_financial_facts(ticker)
        return result.model_dump(mode="json")

    return get_financial_facts
