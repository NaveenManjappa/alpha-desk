# ADR 014: OpenAI as the default provider, set by configuration

Status: Accepted · 12 Nov 2026 · Supersedes [ADR 004](004-llm-provider-and-model-tiers.md)

## Context

ADR 004 chose Azure OpenAI. Before any model code was written, setup friction became a concern. Azure OpenAI needs a resource, a model deployment and quota before the first call. The project is built and run locally first, so a simpler start matters more than cloud alignment at this stage.

The two-tier idea from ADR 004 still holds. Only the provider changes.

## Options considered

| Option | For | Against |
|---|---|---|
| Azure OpenAI only | Common in regulated industries. Built-in content filter. One cloud account. | More setup before the first call. New models can arrive later. |
| OpenAI only | One API key. Simple setup. Newest models first. | No path to Azure without code changes. |
| OpenAI by default, provider chosen by config | Simple start. Azure OpenAI remains one setting away. | Two providers to test before claiming both work. |

## Decision

Use OpenAI's API by default. The provider is a setting with two allowed values: `openai` and `azure_openai`.

- **Small tier:** Supervisor routing, Market Data, News, Risk, Portfolio Manager.
- **Large tier:** Fundamentals Analyst, Compliance Critic, final brief writing.

Model names for each tier live in configuration, not code. A second model acts as a fallback when the first is rate limited or down.

## Consequences

- All model access goes through one factory module. It is the only place that knows which provider is in use.
- Azure-specific settings (endpoint, API version, deployment name) are read only when the provider is `azure_openai`.
- OpenAI has no always-on content filter in the way Azure OpenAI does. If that base layer is wanted, the app calls OpenAI's moderation endpoint itself (see ADR 012).
- Running on Azure OpenAI is verified in Phase 7. Until then it is supported by design, not by test.
- Token counts and cost are recorded per agent, so we can see where money goes.
- Changing a model or a provider is a behaviour change. The eval suite must pass before it is accepted.
- Stable system prompts are placed first in each request so the provider's prompt cache can reuse them.

## In short

"The provider is a config value behind one factory. I build on OpenAI because setup is simple, and Azure OpenAI is one setting away for environments that require it. Evals gate any model or provider change."
