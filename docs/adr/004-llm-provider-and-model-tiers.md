# ADR 004: Azure OpenAI with two model tiers

Status: Superseded by [ADR 014](014-openai-default-provider.md) · 12 Nov 2026 (accepted 10 Nov 2026)

The two-tier decision below still stands. The provider choice was replaced.

## Context

LLM calls are the only real running cost. Different steps need different strength. Routing a question is easy. Analysing a filing is hard.

## Options considered

| Option | For | Against |
|---|---|---|
| One strong model everywhere | Simple. Best quality on every step. | Expensive and slower. Wasteful on easy steps. |
| One small model everywhere | Cheap and fast. | Weak on analysis and critique. |
| Two tiers, chosen per agent | Cost follows difficulty. | One more thing to configure and evaluate. |

Provider: Azure OpenAI, to match an Azure-first profile and common enterprise practice in UK finance.

## Decision

Use Azure OpenAI with two tiers.

- **Small tier:** Supervisor routing, Market Data, News, Risk, Portfolio Manager.
- **Large tier:** Fundamentals Analyst, Compliance Critic, final brief writing.

Model names live in configuration, not code. A second deployment acts as a fallback when the first is rate limited or down.

## Consequences

- All model access goes through one small factory module, so swapping provider is a config change.
- Token counts and cost are recorded per agent, so we can see where money goes.
- Changing a model is a behaviour change. The eval suite must pass before a model swap is accepted.
- Stable system prompts are placed first in each request so the provider's prompt cache can reuse them.

## In short

"I matched model strength to task difficulty and measured cost per agent. Model names are config, and evals gate any model change."
