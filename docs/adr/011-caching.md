# ADR 011: Redis with three cache types and data-aware keys

Status: Accepted · 10 Nov 2026

## Context

LLM calls and market data calls cost money and time. Much of the work repeats: the same quote, the same filing section, the same question about the same company.

## Options considered

| Option | For | Against |
|---|---|---|
| No cache | Always fresh. | Slow and costly. Hits rate limits. |
| In-process cache | Zero setup. | Lost on restart. Not shared between services. |
| Redis | Shared, fast, built-in expiry. The standard choice. | One more service. |

## Decision

Use Redis. Locally it is a container. The optional deploy uses Upstash's free plan.

| Cache | What | Lifetime |
|---|---|---|
| Prompt cache | Stable system prompts and tool definitions | Managed by the LLM provider |
| Tool-result cache | Quotes, ratios, filing sections | Quotes: minutes. Filings: days. |
| Semantic cache | Answers to near-identical research questions | Until the underlying data changes |

## Key design

A cache key includes what the answer depends on.

- Quote: ticker plus a time bucket.
- Filing section: ticker, form, period, section.
- Semantic cache: ticker, latest filing date, and price date. A new filing or a new trading day gives a new key, so stale answers are never served.

## What is never cached

Portfolio state, order status, and anything personal to one user in a shared key. Stale data there is a correctness bug.

## Consequences

- If Redis is down, the app still works, only slower. The cache is never the source of truth.
- Cache hits and misses are logged, so savings can be shown with numbers.
- The semantic cache is the riskiest. It ships last, behind a flag, with an eval that checks it never returns an answer for the wrong company.
- Upstash's free plan has a monthly command limit. Normal demo use sits far below it.

## In short

"I cache at three levels and put the data version in the key, so invalidation is automatic. I never cache anything where stale means wrong, like a portfolio balance."
