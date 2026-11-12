"""Tests for the get_quote tool, called the way an agent would call it. No network:
the real client and service sit on top of an in-memory httpx transport."""

import httpx
import pytest
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool

from alphadesk.integrations.finnhub import FinnhubClient
from alphadesk.services.quotes import QuoteService
from alphadesk.tools.quote_tool import make_get_quote_tool


def _tool(response: httpx.Response) -> BaseTool:
    http = httpx.AsyncClient(
        base_url="https://finnhub.io/api/v1",
        transport=httpx.MockTransport(lambda _: response),
    )
    return make_get_quote_tool(QuoteService(FinnhubClient(http)))


APPLE = httpx.Response(200, json={"c": 227.5, "d": 1.25, "dp": 0.55, "t": 1_762_966_800})


@pytest.mark.unit
def test_tool_exposes_name_description_and_ticker_argument_to_the_model() -> None:
    tool = _tool(APPLE)

    assert tool.name == "get_quote"
    assert "share price" in tool.description
    assert "Args:" not in tool.description  # argument docs move into the schema
    assert "AAPL" in tool.args["ticker"]["description"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_success_returns_quote_with_source_and_as_of() -> None:
    result = await _tool(APPLE).ainvoke({"ticker": "AAPL"})

    assert result["ticker"] == "AAPL"
    assert result["price"] == 227.5
    assert result["source_url"] == "https://finnhub.io/api/v1/quote?symbol=AAPL"
    assert "as_of" in result
    assert "quote_time" in result


@pytest.mark.unit
@pytest.mark.asyncio
async def test_bad_input_returns_error_as_data() -> None:
    result = await _tool(APPLE).ainvoke({"ticker": "not a ticker!"})

    assert result["error_type"] == "invalid_input"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unknown_ticker_returns_error_as_data() -> None:
    unknown = httpx.Response(200, json={"c": 0, "d": None, "dp": None, "t": 0})

    result = await _tool(unknown).ainvoke({"ticker": "ZZZZZ"})

    assert result["error_type"] == "not_found"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_upstream_failure_returns_error_as_data_in_a_tool_message() -> None:
    # Called with a tool-call dict, exactly as the agent loop will call it in Slice 4.
    tool_call = {
        "name": "get_quote",
        "args": {"ticker": "AAPL"},
        "id": "call-1",
        "type": "tool_call",
    }

    message = await _tool(httpx.Response(500)).ainvoke(tool_call)

    assert isinstance(message, ToolMessage)
    assert '"error_type": "upstream_error"' in message.text
