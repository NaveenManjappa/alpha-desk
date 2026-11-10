# ADR 002: Supervisor pattern with one handoff

Status: Accepted · 10 Nov 2026

## Context

Research needs several skills: reading filings, pulling market data, scanning news, checking risk. We must decide how agents are organised and who is in charge.

## Options considered

| Option | For | Against |
|---|---|---|
| One agent with all tools | Simplest. Fewest LLM calls. | Long prompt, many tools, weaker tool choice. No parallelism. Write access sits next to read access. |
| Supervisor with specialist workers | Clear owner of the plan. Workers run in parallel. Each has a small tool set. | More LLM calls. The supervisor can become a bottleneck. |
| Peer-to-peer swarm (agents hand off freely) | Flexible. No central bottleneck. | Hard to predict and debug. Loops are possible. |

## Decision

Use a supervisor for research. Use one explicit handoff, from research to the Portfolio Manager, when the user asks to trade.

## Why a handoff for trading

Research and trading are different modes. Research is read-only and open-ended. Trading is narrow and can change state. A handoff moves control to an agent with a different prompt, different tools and stricter rules. The research agents never see write tools.

## Consequences

- Phase 1 still starts with a single agent. The supervisor arrives in Phase 3, so we can compare cost and quality before and after.
- More agents means more tokens. The router sends simple questions to one analyst only.
- The handoff passes a short typed summary, not the whole message history.

## In an interview

"I started with one agent and only split when I had a reason: parallel research, smaller tool sets, and keeping write access away from research. Multi-agent costs more, so simple questions still take the short path."
