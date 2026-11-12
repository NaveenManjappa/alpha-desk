# Architecture Decision Records

Each ADR records one decision: the problem, the options, the choice, and what it costs. They are short on purpose. If a decision changes, add a new ADR that replaces the old one. Do not rewrite history.

| # | Decision | Status |
|---|---|---|
| [001](001-orchestration-framework.md) | LangGraph for orchestration | Accepted |
| [002](002-multi-agent-pattern.md) | Supervisor pattern with one handoff | Accepted |
| [003](003-tools-and-mcp.md) | Plain function tools first, MCP from Phase 2 | Accepted |
| [004](004-llm-provider-and-model-tiers.md) | Azure OpenAI with two model tiers | Accepted |
| [005](005-postgres-as-system-of-record.md) | One Postgres database for state, memory and business data | Accepted |
| [006](006-vector-store.md) | Qdrant as the vector store | Accepted |
| [007](007-market-data-provider.md) | Finnhub free tier for market data and news | Accepted |
| [008](008-tracing-and-evals.md) | LangSmith for tracing, DeepEval plus code checks for evals | Accepted |
| [009](009-trade-approval.md) | Approval as a custom graph node, order placed by code | Accepted |
| [010](010-idempotency.md) | Idempotency key created with the proposal, enforced by the broker | Accepted |
| [011](011-caching.md) | Redis with three cache types and data-aware keys | Accepted |
| [012](012-guardrails.md) | NeMo Guardrails for input, code for tool and output rules | Accepted |
| [013](013-running-and-hosting.md) | Local-first with Docker Compose, optional free-tier deploy | Accepted |

Template for new ADRs: Context, Options considered, Decision, Consequences, In short.
