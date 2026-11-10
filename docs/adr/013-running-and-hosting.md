# ADR 013: Local-first with Docker Compose, optional free-tier deploy

Status: Accepted · 10 Nov 2026

## Context

This is a portfolio project. Running cost should be zero, apart from LLM calls. It must still be easy for someone else to run and for the owner to demo.

## Options considered

| Option | For | Against |
|---|---|---|
| Always-on cloud deployment | A live URL at all times. | Monthly cost for databases and compute. |
| Local only | Free. Simple. | No live URL. No deployment story. |
| Local first, optional deploy on free tiers | Free. Still shows deployment skill. | Free tiers have limits and idle rules. |

## Decision

**Local first.** `docker compose up` starts the API, three MCP servers, Postgres, Qdrant and Redis.

**Optional deploy in Phase 7**, on free tiers:

| Piece | Provider | Note |
|---|---|---|
| API and MCP servers | Azure Container Apps | Scale to zero. Minimum replicas set to 0. |
| Postgres | Neon | Sleeps when idle, wakes on the next query. |
| Qdrant | Qdrant Cloud | Pauses after seven idle days. |
| Redis | Upstash | Monthly command limit. |

**Qdrant keep-alive.** A scheduled GitHub Actions workflow sends one read-only request every two days. Credentials are GitHub secrets. It fails loudly if the cluster does not answer. It is built in Phase 7.

## Consequences

- Local and cloud use the same containers and the same settings names. Only the connection values differ.
- The first request after idle is slow, because services wake from zero. Acceptable for a demo.
- Free tiers change. Recheck each provider's pricing page, and Qdrant's free-tier terms on keep-alive requests, before deploying.
- A budget alert in Azure guards against surprise spend.
- The README includes a recorded demo, so the project can be judged without running it.

## In an interview

"It runs anywhere with one command, and the cloud version costs nothing when idle because everything scales to zero. I designed for the constraint I actually had, which was cost."
