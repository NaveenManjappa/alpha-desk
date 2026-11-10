# ADR 003: Plain function tools first, MCP from Phase 2

Status: Accepted · 10 Nov 2026

## Context

Agents need tools for market data, filings and the paper broker. Tools can live inside the app as Python functions, or outside it behind MCP servers.

## Options considered

| Option | For | Against |
|---|---|---|
| Plain Python function tools | Simple, fast, easy to test. | Tied to this app and this framework. |
| MCP servers | Standard interface. Tools run as separate services. Reusable from any MCP client. Per-server access control. | Extra network hop. More services to run and monitor. |

## Decision

Phase 1 uses plain functions. Phase 2 moves them behind three MCP servers: `market-data`, `filings` and `paper-broker`. Servers are built with FastMCP and served over HTTP. Agents connect through LangChain's MCP client.

## Consequences

- We can show the same tool both ways and explain the difference from experience.
- The broker server can be demonstrated from another MCP client, such as Claude Desktop.
- Each agent is given only the tools it needs. Analysts never receive write tools.
- LangChain's MCP client (`langchain.mcp`) is in beta, so its API may change. All MCP client code sits in one module, `tools/`, to contain that risk.
- Tool logic lives in `services/`. The MCP server is a thin wrapper, so the logic is testable without MCP.

## In an interview

"MCP is worth it when tools are shared, owned separately, or need their own access rules. For a small single app, plain functions are simpler. I built both so I could show where the line is."
