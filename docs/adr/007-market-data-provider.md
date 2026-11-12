# ADR 007: Finnhub free tier for market data and news

Status: Accepted · 10 Nov 2026

## Context

The app needs current prices, price history, earnings dates and company news for US stocks. It must cost nothing. Real-time accuracy is not needed, because trading is simulated.

## Options considered

| Option | For | Against |
|---|---|---|
| Finnhub free tier | Generous per-minute limit. Prices and news from one account. | Free quotes may be delayed. Limited history. |
| Alpha Vantage free tier | Well known, easy to start. | Very low daily request limit. One research run could use it up. |
| Twelve Data free tier | Reasonable daily limit. | Delayed data. No news. |
| Unofficial scraping libraries | No key needed. | Unofficial, can break without warning, unclear terms. Not a production choice. |

## Decision

Use Finnhub's free tier, behind the `market-data` MCP server.

## Consequences

- Ratios such as P/E are calculated in code from the price plus figures from SEC EDGAR. We do not depend on a provider's premium fundamentals.
- Every quote carries its timestamp, and the brief shows it.
- Results are cached (ADR 011) to stay well inside rate limits.
- The provider is hidden behind the MCP server. Swapping it touches one client in `integrations/`. The client translates the provider's responses and failures into provider-neutral domain types (`MarketQuote`, `MarketDataError`), so services never see provider types.
- Free tiers and their terms change. Confirm Finnhub's current limits and usage terms on its own site before building Phase 2.

## In short

"For paper trading, delayed quotes are fine, so I optimised for cost and rate limits. I show the data's age to the user and keep the provider swappable."
