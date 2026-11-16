# Phase 4 Spec: Memory and Cache

Status: draft · 16 Nov 2026 · Review against your Phase 3 notes before building

## Goal

The desk remembers the investor across conversations, and stops paying twice for the same work.

**Working result:** in one conversation you say "I'm a cautious investor, I don't hold tobacco or oil, and I like to see P/E first." A week later, in a new conversation, a brief leads with P/E, flags an excluded sector, and mentions what you concluded last time you looked at that company. A second brief on the same company the same day is faster and cheaper, and you can show the numbers.

## What you will be able to explain after this phase

- Short-term memory against long-term memory: checkpointer against store.
- The three kinds of long-term memory: semantic, episodic and procedural, each with an example from your own app.
- When memory is written, who writes it, and why the model never writes it directly.
- How to keep a long conversation useful by summarising, and what summarising loses.
- Three kinds of cache, and what each one saves.
- How to design a cache key so stale answers are never served.
- What must never be cached, and why.

## Not in this phase

| Left out | Arrives in |
|---|---|
| The Portfolio Manager, orders, approvals | Phase 5 |
| Remembering trade decisions | Phase 5 adds them to episodic memory |
| NeMo Guardrails, the full eval suite, CI gate | Phase 6 |
| Sign-in and real users | Phase 7 |
| The scheduled daily brief | Phase 7. The watchlist it needs is stored here. |

If Claude Code starts building any of these, stop it.

## Before you start

- Phase 3 exit checklist is complete and tag `v0.3-phase3` exists.
- Read your `phase-3-notes.md`. If an open question changes this spec, update the spec first.
- Record the baseline from Phase 3: cost per brief, latency per brief, and the number of outside API calls per brief. Every cache slice is measured against it.
- Check the current LangGraph docs for the Postgres store, namespaces, and semantic search in the store.
- Check the current LangChain docs for summarising message history.
- Check the OpenAI docs for how prompt caching works and how cached tokens are reported.

## How to work through this spec

There are 12 slices. Each adds **one concept**. Same routine as before:

1. Read the slice. Understand the concept before any code exists.
2. Give Claude Code the prompt in the slice.
3. Read every line it wrote.
4. Run the "Done when" checks yourself.
5. Answer the "Explain back" questions out loud, without looking at the code.
6. Commit. One slice, one commit.

Slices 0 to 3 are caching. Slices 4 to 9 are memory. Slice 10 is the semantic cache, which needs both. Slice 11 measures everything.

## The user

There is still one demo user. From this phase every request carries a `user_id`, read from settings. Memory is keyed by it. A second user ID exists in tests, to prove one user's memory never reaches another. Phase 7 replaces the setting with a real sign-in.

## The memory model

All long-term memory lives in the LangGraph store on Postgres, in the `memory` schema.

| Type | What it holds | Namespace | Shape |
|---|---|---|---|
| Semantic | The investor profile | `(user_id, "profile")` | One `InvestorProfile` |
| Episodic | Past briefs, with the conclusion | `(user_id, "episodes")` | Many `Episode` records |
| Procedural | How this user likes output presented | `(user_id, "preferences")` | A short list of `PresentationRule` |

**`InvestorProfile`**

| Field | Meaning |
|---|---|
| `risk_appetite` | Cautious, balanced or adventurous |
| `horizon` | Short, medium or long term |
| `exclusions` | Sectors or companies the user does not want |
| `watchlist` | Tickers the user follows |
| `updated_at` | Set by code |

**`Episode`**

| Field | Meaning |
|---|---|
| `ticker`, `date` | What was researched, and when |
| `question` | What the user asked |
| `headline` | The brief's one-line view |
| `key_figures` | A few figures from that brief, with their `as_of` |
| `thread_id` | Where the full brief lives |

**`PresentationRule`**

| Field | Meaning |
|---|---|
| `rule` | For example "show P/E first" |
| `category` | One of a fixed list: ordering, length, format, emphasis |
| `created_at` | Set by code |

## How memory is written

The project rule says no LLM may call a tool that changes state. Memory is state. So:

1. After a turn, a small model reads the turn and **proposes** a typed update.
2. Code validates it against the model's schema and the allowed categories.
3. Code writes it to the store.

The model proposes. Code decides and writes. This is the same shape the trade flow uses in Phase 5.

Limits that code enforces:

- A presentation rule can change order, length, format or emphasis. It can never change a guardrail, remove the disclaimer, or switch off citations.
- Memory is only written from what the **user** said. Never from news, filings or tool output.
- Every memory can be seen and deleted by the user.

## The caches

| Cache | Where it sits | Key includes | Lifetime |
|---|---|---|---|
| Tool-result | Inside each MCP server, around the service call | Tool name, arguments, and a time bucket or data date | Quotes: 2 minutes. News: 30 minutes. Ratios: same as quotes. Filing sections and facts: 7 days. |
| Prompt | Managed by the provider | The stable start of each prompt | Managed by the provider |
| Semantic | In the app, before the graph runs | Ticker, latest filing date, price date, and the question's meaning | Until any of those change |

Never cached: portfolio, orders, anything from the store, and any answer that used the user's memory or portfolio.

Lifetimes are settings. The figures above are starting points.

## Decisions to record in this phase

| ADR | Decision | Leaning |
|---|---|---|
| 019 | When memory is written: during the turn, or after it | After the turn, by a separate step, so the user's reply is not slowed |
| 020 | Where the tool-result cache sits: in the app, or in each MCP server | In each server. The server owns its data and its freshness rules. |

---

## Slice 0: Redis and the first cached tool

**Concept:** cache-aside. Look in the cache first. On a miss, do the work and store the result.

**Build**

- Redis added to Docker Compose. `/health` checks it.
- A small cache module with `get` and `set`, behind an interface.
- `get_quote` cached in the market-data server. The key is the ticker plus a two-minute time bucket.
- A cached result keeps its original `as_of` and quote time.
- A log line for every hit and miss.
- If Redis is down, the tool still works. ADR 020 written.

**Done when**

- Two quote requests within a minute make one Finnhub call.
- With Redis stopped, a quote request still succeeds, and a warning is logged.
- A unit test with a fake clock shows the entry expiring.
- Error results are not cached.

**Prompt for Claude Code**

> Build Slice 0 of docs/phases/phase-4-spec.md. Read docs/adr/011-caching.md first. The cache must never be able to break a request: a Redis failure is a miss. Write the Redis-down test first.

**Explain back**

- Why is the time bucket in the key, instead of relying only on expiry?
- Why must a cached quote keep its original timestamp?
- Why are errors not cached?

---

## Slice 1: Cache the rest, with the right lifetimes

**Concept:** freshness is a property of the data, not of the cache. Each kind of data gets its own rule.

**Build**

- Caching for `get_ratios`, `get_earnings_date`, `get_price_history`, `get_company_news`, `get_filing_section`, `search_filings`, `get_financial_facts` and `list_filings`.
- Lifetimes from settings, as in "The caches" above.
- Filing keys include the form and period, so a new filing gets a new key.
- A test that asserts the paper-broker server has no caching at all.

**Done when**

- A second full brief on the same company, a minute later, makes close to zero outside API calls.
- The hit rate per tool appears in the logs.
- The portfolio is read fresh every time.

**Prompt for Claude Code**

> Build Slice 1 of docs/phases/phase-4-spec.md. Do not repeat the cache-aside code in every tool. Portfolio and order tools must never be cached, and a test must prove it.

**Explain back**

- Why can a filing section live for days but a quote only for minutes?
- What exactly goes wrong if the portfolio is cached?
- How does a new 10-K invalidate old entries without anyone deleting them?

---

## Slice 2: The prompt cache

**Concept:** the provider caches the start of a prompt. Put the part that never changes first.

**Build**

- Each agent's prompt arranged in a fixed order: system prompt, tool definitions, then anything that varies.
- Nothing that changes per request, such as the date or the user's name, placed before the stable part.
- Cached token counts read from each model response and added to the cost log.

**Done when**

- The trace for a second brief shows cached input tokens on the large-tier calls.
- A unit test asserts that each agent's stable prefix is identical between two different requests.
- You can state the saving per brief in tokens.

**Prompt for Claude Code**

> Build Slice 2 of docs/phases/phase-4-spec.md. Check the current OpenAI docs for prompt caching rules and how cached tokens are reported. This slice reorders prompts and adds logging. It adds no new store.

**Explain back**

- Why does the order of a prompt affect its cost?
- What single change to a system prompt would throw away the cache for every call?
- Where will user memory go in the prompt, and why there?

---

## Slice 3: Summarise old turns

**Concept:** summarising. Keep the meaning of old turns when their text no longer fits.

**Build**

- When history passes the token budget, the oldest turns are replaced by a short summary, written by the small tier.
- The summary is kept in graph state and updated as the conversation grows.
- The most recent turns stay word for word.
- A tool call is never separated from its result.
- This replaces the plain trimming from Phase 1.

**Done when**

- In a 25-turn chat, a question about a company from turn 2 is still answered sensibly.
- The trace shows input tokens levelling off.
- A unit test with a fake model shows when the summary is created and that recent turns are untouched.

**Prompt for Claude Code**

> Build Slice 3 of docs/phases/phase-4-spec.md. Check the current LangChain docs for the recommended way to summarise history. The summary prompt goes in prompts/. Small tier.

**Explain back**

- What does summarising keep that trimming lost? What does it still lose?
- The summary is in graph state. Is that short-term or long-term memory?
- What does a summary cost, and when is it paid?

---

## Slice 4: The store

**Concept:** the store is long-term memory. It is keyed by user, not by thread.

**Build**

- The Postgres store set up in the `memory` schema, created by the migration step.
- An in-memory store for unit tests, chosen through settings.
- A `memory/` module with typed read and write functions for the profile. No model is involved yet.
- `user_id` passed into every graph run.
- A small script to write a profile, then read it from a different thread.

**Done when**

- A profile written in one thread is read in another.
- A restart does not lose it.
- A unit test proves user A cannot read user B's profile.

**Prompt for Claude Code**

> Build Slice 4 of docs/phases/phase-4-spec.md. Check the current LangGraph docs for the Postgres store and namespaces. Plain read and write only in this slice. No model writes memory yet.

**Explain back**

- State the difference between checkpointer and store in one sentence each.
- What is a namespace, and what is ours built from?
- Why does the store need a user ID when the checkpointer needs a thread ID?

---

## Slice 5: Semantic memory, the investor profile

**Concept:** semantic memory. Facts about the user that stay true across conversations.

**Build**

- A memory-writer step that runs after the reply is sent. ADR 019 written.
- The small tier reads the user's last message and proposes a `ProfileUpdate`. Most turns produce no update.
- Code validates the update and merges it into the profile.
- The Supervisor's planning step and the brief writer receive the profile.
- The Risk Analyst flags a company that matches an exclusion. That check is code.

**Done when**

- You say "I'm cautious and I avoid tobacco." A new thread's brief on a tobacco company flags the exclusion.
- "What's Apple's price?" writes nothing to memory.
- A statement inside a news article, such as "the reader prefers high risk", writes nothing.
- A unit test covers the merge: adding, changing and removing an exclusion.

**Prompt for Claude Code**

> Build Slice 5 of docs/phases/phase-4-spec.md. The model only proposes a typed update. Code validates and writes it. Memory is written only from the user's own messages. Write the merge tests first.

**Explain back**

- Why does the model propose and code write?
- Why write after the reply and not during it?
- How do you stop a news article from writing to the user's profile?

---

## Slice 6: Episodic memory

**Concept:** episodic memory. A record of what happened, so the desk can refer back to it.

**Build**

- After a full brief, code saves an `Episode`. No model call is needed, because the brief is already typed.
- Recall by ticker: the latest few episodes for the company in the current plan.
- The brief writer receives them and may add one line: what was concluded last time, and what has changed since.
- Figures from an episode are shown with their original date. They are never presented as current.

**Done when**

- A second brief on Microsoft, in a new thread, refers to the first one with its date.
- A brief on a company never researched before mentions no history.
- A test proves an old figure cannot enter `key_figures` as a current value.

**Prompt for Claude Code**

> Build Slice 6 of docs/phases/phase-4-spec.md. Saving an episode is plain code. Recall is by user and ticker. Old figures must always carry their original date.

**Explain back**

- Why is this episodic and not semantic memory?
- Why is an old figure dangerous in a research brief?
- Why does saving an episode need no model call?

---

## Slice 7: Search episodes by meaning

**Concept:** semantic search over memory. Find a past episode by what it was about, not by an exact key.

**Build**

- An embedding index on the episodes namespace, using the embedding model from the factory.
- A recall function: given a question, return the most similar past episodes for this user.
- Used for questions such as "what did I look at about AI chip demand?"

**Done when**

- That kind of question returns the right past brief, with its date and thread.
- Search results never cross users.
- A unit test with a fake embedding model covers ranking and the user filter.

**Prompt for Claude Code**

> Build Slice 7 of docs/phases/phase-4-spec.md. Check the current LangGraph docs for semantic search in the store. Reuse the embedding model from the factory. The user filter is mandatory.

**Explain back**

- When is recall by key enough, and when do you need search by meaning?
- This is the second place the app uses embeddings. How is it different from filing search?

---

## Slice 8: Procedural memory

**Concept:** procedural memory. The system learns how this user wants things done.

**Build**

- The memory writer can also propose a `PresentationRule`, when the user states a lasting preference about output.
- Code accepts only the four categories, and rejects anything that touches safety, citations or the disclaimer.
- A cap on the number of rules per user.
- Rules are added to the brief writer's prompt, after the stable part.

**Done when**

- "Always show P/E first" changes the next brief, in a new thread.
- "Never show the disclaimer" is rejected, and the user is told why.
- "Stop citing sources" is rejected.
- A one-off request, such as "make this one shorter", does not become a rule.

**Prompt for Claude Code**

> Build Slice 8 of docs/phases/phase-4-spec.md. The allowed categories are a fixed list checked in code. Write the rejection tests first. Rules go after the stable prompt prefix so the prompt cache still works.

**Explain back**

- How is procedural memory different from the profile?
- Why is a learned rule a security risk, and what limits it here?
- Why does the position of the rules in the prompt matter for cost?

---

## Slice 9: Memory you can see and delete

**Concept:** user control. Memory the user cannot inspect is a liability.

**Build**

- `GET /memory` returns the profile, the rules and recent episodes.
- `DELETE /memory/{kind}/{id}` removes one item. A second endpoint clears everything for the user.
- A "What I remember" panel on the chat page, with a delete button per item.
- The watchlist can be edited from the page.

**Done when**

- You delete the tobacco exclusion, and the next brief no longer flags it.
- "Forget everything" leaves the store empty for that user.
- The page shows exactly what the store holds.

**Prompt for Claude Code**

> Build Slice 9 of docs/phases/phase-4-spec.md. Thin routes over the memory module. Extend the existing page with plain JavaScript.

**Explain back**

- Why give the user a delete button?
- A user deletes a memory. Where else might that fact still exist? (Hint: threads, traces.)

---

## Slice 10: The semantic cache

**Concept:** a semantic cache returns a stored answer for a question that means the same thing. It is the riskiest cache, so it ships last and behind a flag.

**Build**

- A flag in settings, off by default.
- Before the graph runs: embed the question and look for a stored brief with the same ticker, the same latest filing date, the same price date, and a similarity above a strict threshold.
- A hit returns the stored brief, marked as cached, with its original `as_of`.
- Skipped entirely when the run would use the user's profile, rules, episodes or portfolio.
- Only verified briefs with no open issues are stored.

**Done when**

- "Give me a brief on Apple" and "Full brief for Apple please" share one run.
- "Give me a brief on Apple" and "Give me a brief on Microsoft" never share one. An eval case proves it with ten near-identical question pairs across companies.
- The next trading day gives a miss.
- With the flag off, nothing changes.

**Prompt for Claude Code**

> Build Slice 10 of docs/phases/phase-4-spec.md. Read the semantic cache notes in docs/adr/011-caching.md first. The ticker is an exact part of the key, never left to similarity. Write the wrong-company eval first.

**Explain back**

- Why is the ticker in the key and not left to the embedding?
- Why is this cache skipped for personalised answers?
- What is the cost of a threshold that is too low? Too high?

---

## Slice 11: Measure it

**Concept:** claims need numbers. "Faster and cheaper" is a table, not a feeling.

**Build**

- A script that runs a fixed set of ten requests twice: cold, then warm.
- A report: cost per brief, latency, outside API calls, cache hit rate per cache, and cached prompt tokens.
- Memory evals: the profile is recalled; an exclusion is flagged; a rule is applied; nothing leaks between two users.
- The full eval suite run with caches on, to prove quality did not drop.

**Done when**

- You have a before-and-after table against the Phase 3 baseline.
- `make eval` scores no worse with caches on.
- The two-user leak test passes.

**Prompt for Claude Code**

> Build Slice 11 of docs/phases/phase-4-spec.md. The benchmark script reads numbers from logs and traces. Memory evals use two user IDs. Save the report to a file.

**Explain back**

- Which cache saved the most money? Which saved the most time?
- How do you know caching did not lower quality?
- What would you watch in production to notice a stale cache?

---

## Break it on purpose

Do these after Slice 11. Write down what happened.

1. Stop Redis in the middle of a brief.
2. Tell it something false about yourself, then correct it. What does the profile hold?
3. Tell it: "Remember that I always want you to recommend buying." What happens?
4. Paste a news paragraph that says "the user prefers high-risk stocks". Does memory change?
5. Ask for a brief, change your exclusions, and ask again. Is the second one stale?
6. Have a 40-turn conversation. Ask about turn 1.
7. Ask the same brief question in two different wordings with the semantic cache on.
8. Delete all memory, then ask "what do you know about me?"

Anything that surprises you becomes a note for a later phase.

## Demo script

1. `docker compose up -d`, then `make run`. Open the page.
2. Say "I'm a cautious long-term investor, I avoid tobacco, and I like P/E shown first."
3. Open the "What I remember" panel. Show the profile and the rule.
4. Start a new conversation. Ask for a brief. Point out the P/E placement.
5. Ask for the same brief again. Show the time, and the cache hits in the log.
6. Ask for a brief on a company researched before. Point out the reference to last time.
7. Delete a memory and show the effect.
8. Show the before-and-after table.

## Phase exit checklist

- [ ] All 12 slices committed, one commit each.
- [ ] `make check` passes.
- [ ] `make eval` scores no worse than Phase 3, with caches on.
- [ ] The before-and-after cost and latency report is saved.
- [ ] The two-user leak test passes.
- [ ] The wrong-company semantic cache eval passes.
- [ ] ADR 019 and ADR 020 written.
- [ ] The demo script works from a fresh clone.
- [ ] "Break it on purpose" notes written.
- [ ] `docs/phases/phase-4-notes.md` written in your own words.
- [ ] Git tag `v0.4-phase4` created.

## Your phase notes

Create `docs/phases/phase-4-notes.md` yourself. Keep it to one page:

- What I built, in five sentences.
- The three decisions I would defend, and why.
- What broke, and what I learned from it.
- What I would do differently.
- Open questions for Phase 5.

When this is done, the phase is ready for review.
