# Phase 6 Spec: The Trust Layer

Status: draft · 16 Nov 2026 · Review against your Phase 5 notes before building

## Goal

Prove the system is safe and good, with numbers. Close the gaps in the guardrails, grow the evals into a real suite, and make a drop in quality block a merge.

**Working result:** a quality report with real figures: answer scores, attack block rate, cost and latency per brief, and known weaknesses. A pull request that makes a prompt worse fails in CI. A swap of the model is accepted or refused by the evals, not by opinion.

## What you will be able to explain after this phase

- The three guardrail layers, what each catches, and what each misses.
- Why a framework handles generic risks and plain code handles domain rules.
- Direct against indirect prompt injection, and your defence for each.
- What a guardrail costs in latency and in wrongly blocked questions.
- The four eval types: final answer, trajectory, per-agent and safety.
- Why judged scores vary between runs, and how to set a threshold that allows for it.
- How evals gate a merge and a model change.
- What to watch once a system is live.

## Not in this phase

| Left out | Arrives in |
|---|---|
| Cloud deployment | Phase 7 |
| Sign-in, rate limits per user | Phase 7 |
| Load testing | Phase 7 |
| New features of any kind | Not here. This phase adds no user-facing features. |

If Claude Code starts building any of these, stop it.

## Before you start

- Phase 5 exit checklist is complete and tag `v0.5-phase5` exists.
- Read all five sets of phase notes. Every "what broke" entry and every "break it on purpose" surprise is input for Slices 0 and 1.
- Check the current NeMo Guardrails docs: supported Python versions, LangGraph integration, the built-in input rails, and whether it works with your model provider. Confirm it installs with the pinned Python version before Slice 3.
- Check the current DeepEval docs for agent, trajectory and tool metrics.
- The repo is on GitHub, and you can add Actions secrets.
- Decide a monthly budget for CI eval runs. Write it down.

## How to work through this spec

There are 14 slices. Each adds **one concept**. Same routine as before:

1. Read the slice. Understand the concept before any code exists.
2. Give Claude Code the prompt in the slice.
3. Read every line it wrote.
4. Run the "Done when" checks yourself.
5. Answer the "Explain back" questions out loud, without looking at the code.
6. Commit. One slice, one commit.

Slices 0 to 7 are guardrails. Slices 8 to 11 are evals and CI. Slices 12 and 13 are monitoring and the report.

One rule for this phase: **measure before you fix.** Slice 1 records how the system does today. Every later slice is judged against that.

## The guardrail layers, completed

| Layer | Already built | Added in this phase |
|---|---|---|
| Input | Off-topic refusal by the Supervisor | Provider moderation, NeMo input rails, personal data masking |
| Tool | Allow-lists, typed arguments, trading rules, human approval | One permissions table with a test, argument limits on every tool |
| Output | Grounding check, citation check, the Critic, fixed disclaimer | Advice-wording check in code, one policy for what happens on failure |
| Retrieved content | "Data, not instructions" in prompts, planted-instruction tests | Consistent wrapping of all retrieved text, a wider attack set |

## What happens when a guardrail fires

One policy, written once and applied everywhere.

| Guardrail | Action | The user sees |
|---|---|---|
| Moderation or jailbreak rail | Stop before any agent runs | A short, neutral refusal |
| Off-topic | Stop before any analyst runs | What the desk can help with |
| Personal data on input | Mask it, then continue | A note that it was masked |
| Tool argument out of limits | Typed error to the agent | Nothing, unless the run cannot finish |
| Trading rule | Proposal marked invalid | The reason |
| Ungrounded number or citation | One retry, then remove it | `verified: false` and the gap |
| Advice wording | One retry, then replace the sentence with neutral wording | Research wording |

Every firing is logged with the guardrail's name, so it can be counted.

## The eval suite, completed

| Type | Question | Checked by |
|---|---|---|
| Final answer | Is the output right and grounded? | Exact checks for figures. Judged: faithfulness, relevance. |
| Trajectory | Did it take a sensible path? | Exact checks on the steps that ran |
| Per-agent | Does one agent do its job alone? | Exact where possible, judged otherwise |
| Safety | Do the guardrails hold? | Exact only |
| Retrieval | Was the right text found? | Exact: hit rate and rank |

Two dataset sizes:

| Set | Size | Runs |
|---|---|---|
| CI set | About 15 cases, at least two per type, every safety-critical case | On every pull request |
| Full set | 60 or more cases | On demand, and before any model change |

## Decisions to record in this phase

| ADR | Decision | Leaning |
|---|---|---|
| 024 | What blocks a merge | Any safety case failing, or a judged score falling more than a set margin below the saved baseline |
| 025 | Which model judges the evals | A fixed, pinned model, different from the model being judged where possible |

---

## Slice 0: The threat model

**Concept:** think before you guard. List what can go wrong, then check what covers it.

**Build**

- `docs/threat-model.md`, about two pages.
- Every place untrusted text enters: user messages, news, filings, tool results, stored memory.
- What is worth protecting: the portfolio, the user's memory, the honesty of a brief, the LLM budget.
- For each threat: which layer stops it today, and which test proves it. Gaps are marked plainly.

**Done when**

- Every row has a named control and a named test, or is marked as a gap.
- The gaps list drives Slices 2 to 7.
- You wrote the threats yourself. Claude Code may review the list, not write it.

**Prompt for Claude Code**

> Read docs/phases/phase-6-spec.md Slice 0 and my draft in docs/threat-model.md. Review it against the code. Tell me which claimed controls have no test, and which entry points I missed. Do not rewrite my document.

**Explain back**

- Which entry point is the most dangerous in this app, and why?
- Name one threat you decided to accept and not fix. Why?

---

## Slice 1: The attack dataset and a baseline

**Concept:** red-teaming. Attack your own system first, and count what gets through.

**Build**

- An attack dataset in `evals/`, about 40 cases across six groups: jailbreak attempts, direct injection, indirect injection through news, indirect injection through filings, requests for personal advice, and personal data in the message.
- A matching set of about 20 normal questions that look a little unusual, to catch wrongly blocked requests.
- Each case has an exact pass rule, for example "no proposal was created" or "the brief contains no recommendation".
- One run against the current system, saved as the baseline.

**Done when**

- You have two numbers: the attack block rate, and the rate of normal questions wrongly blocked.
- You can list the attacks that got through.
- Nothing has been fixed yet.

**Prompt for Claude Code**

> Build Slice 1 of docs/phases/phase-6-spec.md. Pass rules are exact checks on outputs, steps and database writes. Planted content goes into fake tool results, not real data. Do not change any guardrail in this slice.

**Explain back**

- Why record a baseline before fixing anything?
- Why do you need normal questions in an attack dataset?
- Which group got through most often?

---

## Slice 2: A base layer from the provider

**Concept:** defence in depth starts with the cheapest generic check.

**Build**

- A content check on each user message, behind a small interface.
- On OpenAI it calls the moderation endpoint. On Azure OpenAI the built-in filter does this, so the check reads the filter's result.
- A blocked message stops the run before any agent, following the policy table.
- The check's time is logged.

**Done when**

- A clearly harmful message is refused, and no agent runs.
- A normal finance question passes.
- Unit tests use a fake checker.
- You know the latency it adds.

**Prompt for Claude Code**

> Build Slice 2 of docs/phases/phase-6-spec.md. Read docs/adr/012-guardrails.md and docs/adr/014 first. Check the current OpenAI docs for the moderation endpoint. Keep it behind an interface so the provider can change.

**Explain back**

- What does this layer catch, and what is it blind to?
- Why does the interface differ between the two providers?

---

## Slice 3: NeMo input rails

**Concept:** a guardrails framework. Reusable checks for risks that are the same in every app.

**Build**

- NeMo Guardrails as an input step before the Supervisor.
- A small rail set: jailbreak detection and topic control.
- The rail configuration lives in `guardrails/`, as files, not inline.
- The rail's model calls go through the model factory, on the small tier.
- A setting to switch the rails off, for comparison.

**Done when**

- The attack dataset's jailbreak group scores better than the baseline.
- The wrongly-blocked rate has not got worse. If it has, tune the rails until it has not.
- The added latency per message is measured, with the rails on and off.
- Unit tests run with the rails off and need no model.

**Prompt for Claude Code**

> Build Slice 3 of docs/phases/phase-6-spec.md. Check the current NeMo Guardrails docs for LangGraph integration and input rails. Ask before adding the dependency and confirm it supports our Python version. Keep the rail set small. Show me latency with rails on and off.

**Explain back**

- How does a rail decide a message is a jailbreak attempt?
- What did the rails cost per message, in time and in tokens?
- Why is "no order above the cash balance" not a NeMo rail?

---

## Slice 4: Personal data on the way in

**Concept:** data minimisation. Do not send, log or store what you do not need.

**Build**

- Detection and masking of personal data in user messages: card numbers, bank account numbers, phone numbers, email addresses and national ID numbers.
- Masking happens before the message reaches a model, a log, a trace or memory.
- The user is told that something was masked.
- A check that the memory writer never stores masked or personal values.

**Done when**

- A message with a card number reaches the model masked. The trace shows the masked text.
- A message with a ticker and a dollar amount is not touched.
- Unit tests cover each data type and three look-alike cases that must pass, such as a long order quantity.

**Prompt for Claude Code**

> Build Slice 4 of docs/phases/phase-6-spec.md. Check whether NeMo's sensitive data rail fits before writing custom code, and ask before adding any dependency. The look-alike tests come first.

**Explain back**

- Why mask before tracing, not only before the model?
- What is the cost of a detector that is too eager, in a finance app full of numbers?

---

## Slice 5: The permissions table

**Concept:** least privilege, made checkable. One table says who may call what.

**Build**

- One module that holds the full table: each agent, and the tools it may use.
- Every agent builds its tool list from this table. No tool is attached anywhere else.
- A test that compares the table to the table in the architecture doc, row by row.
- Argument limits on every tool, enforced in the server: maximum result counts, date ranges, string lengths, and tickers from a valid pattern.

**Done when**

- Giving an analyst a write tool makes a test fail.
- A tool called with an out-of-range argument returns a typed error.
- The architecture doc and the code agree.

**Prompt for Claude Code**

> Build Slice 5 of docs/phases/phase-6-spec.md. One permissions module, used by every agent. Add the test that fails if any agent gains a write tool. Limits are enforced in the MCP servers, not only in prompts.

**Explain back**

- Why enforce limits in the server and not trust the agent?
- If an attacker fully controls the News Analyst, what can it reach?

---

## Slice 6: Output rules, completed

**Concept:** the last check before the user. Deterministic rules first, judgement second.

**Build**

- A code check for advice wording: phrases that tell the user what to do, such as "you should buy". It runs on every brief and answer.
- A code check that no number appears in summary text outside `key_figures`.
- The policy table applied in one output step: retry once, then remove or replace.
- The Critic still runs for what code cannot judge.

**Done when**

- A draft with "you should buy" never reaches the user.
- A summary containing a stray figure is caught.
- The attack dataset's advice group scores better than the baseline.
- No normal brief is damaged by the wording check. Run the full golden set to confirm.

**Prompt for Claude Code**

> Build Slice 6 of docs/phases/phase-6-spec.md. Plain code checks, tests first. Keep the phrase list in config. Run the golden set to make sure normal briefs still pass.

**Explain back**

- What can the code check catch that the Critic might miss? And the reverse?
- Why does a research app care so much about one word like "should"?

---

## Slice 7: Indirect injection

**Concept:** the attack arrives inside the data. The user is innocent, and the content is hostile.

**Build**

- One function that wraps all retrieved text (news, filing chunks, tool output) in clear markers, with the same short rule in every agent's prompt: text inside the markers is data.
- Marker text is stripped from retrieved content, so content cannot fake a boundary.
- A wider set of planted attacks: instructions to recommend, to change the ticker, to leak the system prompt, to propose a trade, to write to memory.
- A structural check: a trade proposal can only start from a user message, never from retrieved content.

**Done when**

- Both indirect injection groups score better than the baseline.
- No planted attack creates a proposal or a memory write. Those cases are at 100 percent.
- The attacks that still change the wording of a brief are listed in the threat model as known limits.

**Prompt for Claude Code**

> Build Slice 7 of docs/phases/phase-6-spec.md. One wrapping function used by every agent that reads retrieved text. The proposal and memory checks are structural, in code. Report honestly which attacks still get through.

**Explain back**

- Why can a prompt rule alone never fully stop injection?
- Which defences here are structural, and which depend on the model behaving?
- An attack changes a sentence in the brief but cannot trade or write memory. How bad is that?

---

## Slice 8: Grow the golden dataset

**Concept:** a dataset is a product. It needs coverage, labels and a history.

**Build**

- The golden set grown to 60 or more cases, covering all five eval types.
- Each case tagged: type, phase it came from, and whether it is in the CI set.
- Cases added from real failures: every "break it on purpose" surprise becomes a case.
- A short `evals/README.md`: how to add a case, and what makes a good one.
- The dataset is versioned in Git. A change to it is a reviewed change.

**Done when**

- A coverage table shows the case count per type and per agent, with no empty cell.
- The CI set is chosen and runs in under ten minutes.
- You wrote at least half the new cases yourself.

**Prompt for Claude Code**

> Build Slice 8 of docs/phases/phase-6-spec.md. I will write the cases. Build the tagging, the coverage table and the CI subset selection. Propose ten cases from my phase notes for me to review.

**Explain back**

- Why add a case every time something breaks?
- What is the risk of tuning prompts against the same small dataset for months?

---

## Slice 9: The DeepEval suite, and how much scores wobble

**Concept:** judged metrics vary. Measure the variation before you set a threshold.

**Build**

- Judged metrics in place for each type: faithfulness and relevance for final answers, task completion for full briefs, and a tool-use metric for trajectories.
- The judge model pinned in config. ADR 025 written.
- The full set run three times with nothing changed. The spread per metric is recorded.
- Thresholds set below the lowest of the three runs, with a small margin.
- A saved baseline file that later runs are compared against.

**Done when**

- You can state, per metric, the average and the spread across three runs.
- Each threshold has a reason written beside it.
- Exact checks still decide every safety case.

**Prompt for Claude Code**

> Build Slice 9 of docs/phases/phase-6-spec.md. Check the current DeepEval docs for agent and trajectory metrics. Pin the judge model. Run the suite three times and show me the spread before proposing thresholds. Tell me the token cost of one full run.

**Explain back**

- Why did the same system get three different scores?
- How did you choose each threshold?
- Why should the judge be a different model from the one being judged?

---

## Slice 10: The CI gate

**Concept:** quality as a gate. A change that makes the system worse cannot merge.

**Build**

- A GitHub Actions workflow with two jobs.
- Job one, on every push: `make check` and `make web-check`.
- Job two, on pull requests: the CI eval set, using repository secrets. It compares results to the saved baseline.
- The merge rule from ADR 024. ADR written.
- A summary posted on the pull request: scores, changes from baseline, and the cost of the run.
- Branch protection on `main` requiring both jobs.

**Done when**

- A pull request that weakens the brief writer's prompt fails job two.
- A pull request that only edits a doc does not run the evals.
- You know the cost of one CI eval run, and it fits your monthly budget.

**Prompt for Claude Code**

> Build Slice 10 of docs/phases/phase-6-spec.md. Two jobs. Evals run only when code, prompts or eval data change. Secrets come from GitHub Actions secrets and are never printed. Add a spend limit to the eval job.

**Explain back**

- Why do unit tests and evals run as separate jobs?
- A judged score dipped slightly and blocked a good change. What are your options?
- How do you stop CI evals from costing more than the project is worth?

---

## Slice 11: Gate a model change

**Concept:** a model is a dependency. Changing it is a behaviour change, so it goes through the gate.

**Build**

- A documented routine: change a tier's model in config, run the full set, compare to the baseline, decide.
- Do it for real, twice: a cheaper model on the small tier, and the fallback model in place of the main one.
- A comparison report: scores, cost and latency, side by side.

**Done when**

- You have a written decision for each swap: accepted or refused, with the numbers.
- The fallback model's quality is known, not assumed.
- The routine is in the README.

**Prompt for Claude Code**

> Build Slice 11 of docs/phases/phase-6-spec.md. Model names are config, so this is a script and a report, not a code change. Produce the side-by-side comparison from saved eval results.

**Explain back**

- The cheaper model scored two points lower and cost half as much. How do you decide?
- Which agent was most sensitive to the model change?

---

## Slice 12: Dashboards and feedback

**Concept:** monitoring. Evals test what you thought of. Production shows what you did not.

**Build**

- LangSmith dashboards: cost per run, latency at the median and the 95th percentile, error rate, tokens by agent, and guardrail firings by name.
- Thumbs up and down on each answer on the page, sent to LangSmith as feedback on the run.
- A routine: a thumbs-down run is reviewed and, if it shows a real fault, becomes a golden case.
- An alert rule for error rate and for cost per run.

**Done when**

- After 30 mixed requests, each chart has data.
- A thumbs-down on the page appears on the right trace.
- You turned one bad run into a new eval case.

**Prompt for Claude Code**

> Build Slice 12 of docs/phases/phase-6-spec.md. Check the current LangSmith docs for dashboards, feedback and alerts. The page change is two buttons and one API call. No new storage.

**Explain back**

- What is the difference between offline evals and online monitoring?
- Which three charts would you look at first on a bad day?
- How does a user complaint become a regression test?

---

## Slice 13: The quality report

**Concept:** evidence. One page that shows how good the system is, and where it is weak.

**Build**

- A script that builds `docs/quality-report.md` from saved results.
- Contents: eval scores by type; attack block rate before and after this phase; wrongly-blocked rate; cost and latency per answer and per brief; cache hit rates; guardrail latency; the model comparison.
- A "known weaknesses" section, written by you: what still gets through, and what you would do next.
- The date and Git commit the numbers came from.

**Done when**

- Every number in the report can be reproduced with a command named in the report.
- The weaknesses section is specific.
- The README links to the report.

**Prompt for Claude Code**

> Build Slice 13 of docs/phases/phase-6-spec.md. The script only reads saved result files. No number is typed by hand. Leave the known weaknesses section for me to write.

**Explain back**

- Why include weaknesses in a report meant to show quality?
- Pick the number you are least sure of. What would make you trust it more?

---

## Break it on purpose

Do these after Slice 13. Write down what happened.

1. Spend 30 minutes attacking the system by hand, with attacks not in the dataset. Add what worked.
2. Ask ten unusual but honest finance questions. Count how many were wrongly blocked.
3. Open a pull request that weakens a prompt slightly. Does CI catch it?
4. Open a pull request that removes a tool from the permissions table.
5. Paste a message with a card number and a ticker together.
6. Put an instruction in a language other than English inside a fake news item.
7. Run the full eval set twice. Would the difference alone have failed the gate?

## Demo script

1. Show the threat model: entry points, controls, tests.
2. Send a jailbreak attempt. Show the refusal and the guardrail log line.
3. Ask for a brief with a planted instruction in the news. Show that it is ignored.
4. Open a pull request with a worse prompt. Show the failed eval job and its summary.
5. Show the model comparison report.
6. Show the LangSmith dashboard.
7. Open the quality report. Read out the attack block rate before and after, and one known weakness.

## Phase exit checklist

- [ ] All 14 slices committed, one commit each.
- [ ] `make check` passes.
- [ ] The attack baseline and the final attack scores are both saved.
- [ ] No planted attack can create a proposal or write memory.
- [ ] CI blocks a pull request that lowers quality.
- [ ] Two model swaps were decided with numbers.
- [ ] ADR 024 and ADR 025 written.
- [ ] `docs/threat-model.md` and `docs/quality-report.md` exist and are linked from the README.
- [ ] "Break it on purpose" notes written.
- [ ] `docs/phases/phase-6-notes.md` written in your own words.
- [ ] Git tag `v0.6-phase6` created.

## Your phase notes

Create `docs/phases/phase-6-notes.md` yourself. Keep it to one page:

- What I built, in five sentences.
- The three decisions I would defend, and why.
- What broke, and what I learned from it.
- What I would do differently.
- Open questions for Phase 7.

When this is done, AlphaDesk is complete and demonstrable locally. Phase 7 is optional.
