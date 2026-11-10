# ADR 008: LangSmith for tracing, DeepEval plus code checks for evals

Status: Accepted · 10 Nov 2026

## Context

We need to see what each run did, and to measure whether the system is good. These are two jobs: observing and judging.

## Options considered

| Option | For | Against |
|---|---|---|
| LangSmith for everything | Deepest LangGraph integration. One tool. | Evals live in a hosted platform, not in the test suite. |
| Langfuse for tracing | Open source, self-hostable. | More setup. Weaker fit with LangGraph than LangSmith. |
| DeepEval for evals | Runs under pytest, so a failed metric fails the build. Has agent and trajectory metrics. | Most metrics use an LLM as judge, so scores can vary between runs. |
| Hand-written checks only | Exact and cheap. | Cannot judge open-ended quality such as faithfulness. |

## Decision

- **LangSmith** for tracing, debugging, and cost and latency per run.
- **DeepEval** for the eval test suite, run locally and in CI.
- **Exact checks in plain code** wherever a right answer exists.

## What is checked how

| Exact check (code) | Judged check (DeepEval) |
|---|---|
| A figure in the brief equals the figure in the filing | Is the brief faithful to the retrieved text? |
| Every number traces to a tool result | Did the run complete the user's task? |
| The expected tool was called | Did the agents follow a sensible plan? |
| An oversized order is refused | Is the answer relevant to the question? |

## Consequences

- Tracing is on from Phase 1. A small golden dataset starts in Phase 1 and grows each phase.
- Unit tests never call an LLM. Evals do, so they are a separate pytest marker and a separate CI job.
- Judged metrics get thresholds with some slack, to absorb run-to-run variation.
- Eval runs cost tokens. The CI dataset stays small. A larger set runs on demand.

## In an interview

"Tracing tells me what happened. Evals tell me whether it was good. For finance I don't trust judged scores alone, so anything with a right answer is checked in code."
