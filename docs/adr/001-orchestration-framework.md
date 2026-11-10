# ADR 001: LangGraph for orchestration

Status: Accepted · 10 Nov 2026

## Context

AlphaDesk needs several agents to work together. Some steps run in parallel. Some loop. One step pauses for a human. A run must survive a crash and resume. We need a framework that makes this control flow explicit.

## Options considered

| Option | For | Against |
|---|---|---|
| LangGraph | Explicit graph of nodes and edges. Built-in checkpointing, pause and resume, streaming. Large ecosystem. | More concepts to learn than a simple agent loop. |
| A role-based agent framework (CrewAI style) | Quick to start. Reads like a team description. | Control flow is mostly hidden. Harder to explain exactly what ran and why. |
| A vendor agent SDK | Small and simple. | Ties orchestration to one model provider. |
| Plain Python, no framework | Full control, nothing hidden. | We would rebuild persistence, resume and streaming ourselves. |

## Decision

Use LangGraph for the graph and LangChain's `create_agent` for individual agents.

## Consequences

- Control flow is visible as a graph, which is easy to draw and explain.
- Checkpointing gives us conversation memory, human approval and crash recovery from one feature.
- We depend on a fast-moving library. Versions are pinned, and upgrades are deliberate.
- Framework imports stay out of `domain/` and `services/`, so business logic survives a framework change.

## In an interview

"I chose a graph framework because my hardest requirements were control-flow ones: parallel work, a bounded review loop, and a pause for human approval. I wanted those to be explicit, not buried in prompts."
