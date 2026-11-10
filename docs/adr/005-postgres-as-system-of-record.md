# ADR 005: One Postgres database for state, memory and business data

Status: Accepted · 10 Nov 2026

## Context

The system stores four kinds of durable data: graph checkpoints, long-term memory, the paper portfolio and orders, and the audit log.

## Options considered

| Option | For | Against |
|---|---|---|
| One Postgres database | One thing to run, back up and reason about. LangGraph has Postgres checkpointer and store. Orders and audit rows can share a transaction. | Different workloads share one database. |
| Separate stores per concern | Each can scale alone. | Far more to operate. No benefit at this size. |
| SQLite | Zero setup. | Weak for concurrent access. Not what production systems use. |

## Decision

Use one Postgres database, with a separate schema for each concern: `checkpoints`, `memory`, `portfolio`, `audit`.

## Consequences

- Local runs use a Postgres container. The optional cloud deploy uses Neon's free plan.
- An order and its audit row are written in one transaction, so they cannot disagree.
- Checkpoints grow with every step. Old threads need a clean-up job to stay inside free storage.
- Business tables are accessed through repositories, so agents never write SQL.

## In an interview

"Checkpointer and store are different things. The checkpointer is per-thread short-term state. The store is cross-thread long-term memory. Both sit in Postgres, next to the business data, because one database is the simplest thing that works at this scale."
