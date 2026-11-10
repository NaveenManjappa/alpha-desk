# ADR 006: Qdrant as the vector store

Status: Accepted · 10 Nov 2026

## Context

Filing chunks need semantic search with filters, for example "Apple, 10-K, 2025, risk factors".

## Options considered

| Option | For | Against |
|---|---|---|
| Qdrant | Purpose-built. Strong metadata filtering. Hybrid search. Runs in Docker. Free cloud cluster. Prior experience. | One more service to run. |
| pgvector in Postgres | No extra service. Vectors next to relational data. | Fewer search features. Uses the small free Postgres storage. |
| Chroma | Very easy to start. | Less suited to a production story. |

## Decision

Use Qdrant. Locally it runs as a container. The optional deploy uses the Qdrant Cloud free cluster.

## Consequences

- Each chunk carries metadata: ticker, form type, period, section. Searches always filter by ticker first.
- The company list is fixed at about 20 companies with recent filings, to stay far below the free cluster's 1 GB of RAM.
- The free cluster pauses after seven idle days. A scheduled keep-alive request prevents that (see ADR 013).
- Vector access sits behind a small interface, so pgvector remains a fallback.

## In an interview

"I picked a dedicated vector store for filtering and hybrid search, and kept it behind an interface. pgvector would be my choice if I wanted one less service."
