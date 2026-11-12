# ADR 009: Approval as a custom graph node, order placed by code

Status: Accepted · 10 Nov 2026

## Context

Placing an order changes state. A human must approve it first. There are two ways to build the pause.

## Options considered

| Option | For | Against |
|---|---|---|
| Approval middleware on the `place_order` tool | Very little code. Built into LangChain. | The LLM still makes the write call. The approval record is generic, not a business object. |
| A custom approval node in the graph | The order proposal is a typed object we store, show and audit. Code places the order, not the LLM. Shows the underlying pause-and-resume mechanism. | More code to write and test. |

## Decision

Use a custom approval node.

1. The Portfolio Manager agent has read-only tools. Its only output is an `OrderProposal`.
2. Code validates the proposal: cash available, size limits, market rules.
3. The proposal is saved with its idempotency key (ADR 010).
4. The graph pauses and shows the proposal to the user.
5. On approval, a plain code node calls the broker. On rejection, the proposal is marked cancelled.

The important point: **the LLM never calls a write tool.** It proposes. Code and a human decide.

## Consequences

- The risky action is fully deterministic and easy to test.
- The audit row links proposal, evidence, approver and order.
- When a paused node resumes, it runs again from its start. So nothing with a side effect sits before the pause in the same node.
- We write more code than the middleware route. The middleware is still worth a short experiment in Phase 5, to compare.

## In short

"The model can only propose a trade. A human approves it and plain code executes it. I kept the write path deterministic because that is the one place a mistake costs money."
