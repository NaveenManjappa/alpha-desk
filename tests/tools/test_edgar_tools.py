"""Tests for the two SEC EDGAR tools, called the way an agent calls them. No network: the
real client and services sit on top of an in-memory httpx transport playing EDGAR."""

from collections.abc import Callable
from typing import Any

import httpx
import pytest
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool

from alphadesk.integrations.sec_edgar import EdgarClient, RateLimiter
from alphadesk.services.filings import FilingsService
from alphadesk.services.financials import FinancialFactsService
from alphadesk.tools.filings_tool import make_list_recent_filings_tool
from alphadesk.tools.financial_facts_tool import make_get_financial_facts_tool

Handler = Callable[[httpx.Request], httpx.Response]

TICKERS = {"0": {"cik_str": 789019, "ticker": "MSFT", "title": "MICROSOFT CORP"}}

FACTS = {
    "facts": {
        "us-gaap": {
            "RevenueFromContractWithCustomerExcludingAssessedTax": {
                "units": {
                    "USD": [
                        {
                            "start": "2025-07-01",
                            "end": "2026-06-30",
                            "val": 300000000000,
                            "accn": "0000950170-26-000077",
                            "form": "10-K",
                            "filed": "2026-07-30",
                        }
                    ]
                }
            }
        }
    }
}

SUBMISSIONS = {
    "filings": {
        "recent": {
            "accessionNumber": ["0000950170-26-000077"],
            "filingDate": ["2026-07-30"],
            "reportDate": ["2026-06-30"],
            "form": ["10-K"],
            "primaryDocument": ["msft-10k_20260630.htm"],
        }
    }
}


def _edgar(data_response: httpx.Response) -> EdgarClient:
    """EDGAR that knows MSFT, and answers every data.sec.gov call with `data_response`."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("company_tickers.json"):
            return httpx.Response(200, json=TICKERS)
        return data_response

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return EdgarClient(http, RateLimiter(max_per_second=1000))


def _facts_tool(response: httpx.Response) -> BaseTool:
    return make_get_financial_facts_tool(FinancialFactsService(_edgar(response)))


def _filings_tool(response: httpx.Response) -> BaseTool:
    return make_list_recent_filings_tool(FilingsService(_edgar(response)))


def _as_tool_call(name: str) -> dict[str, Any]:
    return {"name": name, "args": {"ticker": "MSFT"}, "id": "call-1", "type": "tool_call"}


# --- get_financial_facts ---


@pytest.mark.unit
def test_financial_facts_tool_describes_itself_to_the_model() -> None:
    tool = _facts_tool(httpx.Response(200, json=FACTS))

    assert tool.name == "get_financial_facts"
    assert "revenue" in tool.description
    assert "share price" in tool.description  # says when not to use it
    assert "MSFT" in tool.args["ticker"]["description"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_financial_facts_success_returns_figures_with_sources() -> None:
    result = await _facts_tool(httpx.Response(200, json=FACTS)).ainvoke({"ticker": "MSFT"})

    assert result["ticker"] == "MSFT"
    assert result["source_url"] == "https://data.sec.gov/api/xbrl/companyfacts/CIK0000789019.json"
    assert "as_of" in result
    [revenue] = result["facts"]
    assert revenue == {
        "metric": "revenue",
        "value": 300_000_000_000,
        "unit": "USD",
        "period_start": "2025-07-01",
        "period_end": "2026-06-30",
        "source_url": "https://www.sec.gov/Archives/edgar/data/789019/000095017026000077/"
        "0000950170-26-000077-index.htm",
    }


@pytest.mark.unit
@pytest.mark.asyncio
async def test_financial_facts_bad_input_returns_error_as_data() -> None:
    result = await _facts_tool(httpx.Response(200, json=FACTS)).ainvoke({"ticker": "not a ticker"})

    assert result["error_type"] == "invalid_input"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_financial_facts_upstream_failure_returns_error_in_a_tool_message() -> None:
    message = await _facts_tool(httpx.Response(503)).ainvoke(_as_tool_call("get_financial_facts"))

    assert isinstance(message, ToolMessage)
    assert '"error_type": "upstream_error"' in message.text


# --- list_recent_filings ---


@pytest.mark.unit
def test_filings_tool_describes_itself_to_the_model() -> None:
    tool = _filings_tool(httpx.Response(200, json=SUBMISSIONS))

    assert tool.name == "list_recent_filings"
    assert "10-K" in tool.description
    assert "get_financial_facts" in tool.description  # points elsewhere for figures


@pytest.mark.unit
@pytest.mark.asyncio
async def test_filings_success_returns_filings_with_links() -> None:
    result = await _filings_tool(httpx.Response(200, json=SUBMISSIONS)).ainvoke({"ticker": "MSFT"})

    assert result["source_url"] == "https://data.sec.gov/submissions/CIK0000789019.json"
    assert "as_of" in result
    assert result["filings"] == [
        {
            "form": "10-K",
            "filing_date": "2026-07-30",
            "report_date": "2026-06-30",
            "url": "https://www.sec.gov/Archives/edgar/data/789019/000095017026000077/"
            "msft-10k_20260630.htm",
        }
    ]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_filings_bad_input_returns_error_as_data() -> None:
    result = await _filings_tool(httpx.Response(200)).ainvoke({"ticker": "not a ticker"})

    assert result["error_type"] == "invalid_input"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_filings_upstream_failure_returns_error_in_a_tool_message() -> None:
    message = await _filings_tool(httpx.Response(503)).ainvoke(_as_tool_call("list_recent_filings"))

    assert isinstance(message, ToolMessage)
    assert '"error_type": "upstream_error"' in message.text
