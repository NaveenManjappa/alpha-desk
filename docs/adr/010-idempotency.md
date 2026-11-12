# ADR 010: Idempotency key created with the proposal, enforced by the broker

Status: Accepted · 10 Nov 2026

## Context

An order might be sent twice. The user double-clicks. The network times out and we retry. The process crashes after the broker accepted the order but before we saved the result. Each case must end with exactly one order.

## Options considered

| Option | For | Against |
|---|---|---|
| Do nothing, hope retries are rare | No work. | Duplicate trades. Unacceptable. |
| Check "does a similar order exist?" before placing | Simple idea. | Race conditions. Two legitimate identical orders look like duplicates. |
| Idempotency key, enforced by the receiver | Standard practice in payments. Safe under retries and crashes. | Needs a key stored on both sides. |

## Decision

1. When an `OrderProposal` is created, it gets a unique key (a UUID). The key is saved with the proposal.
2. Every `place_order` call sends that key.
3. The broker stores the key under a unique constraint.
4. Same key, same details: the broker returns the original order. Nothing new is created.
5. Same key, different details: the broker rejects the call as a conflict.

## Why the key is created early

The key must be the same on every attempt. If it were generated at call time, a retry would produce a new key and a second order. Creating it with the proposal, before the approval pause, makes it stable across retries, resumes and restarts.

## Consequences

- Retries are safe, so the execution node can retry on timeouts.
- After a crash, the graph resumes and calls again with the same key. The broker returns the existing order.
- A test proves it: call `place_order` twice with one key, expect one order.

## In short

"At-least-once delivery plus an idempotent receiver gives exactly-once effect. The key belongs to the intent, the proposal, not to the attempt."
