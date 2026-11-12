# ADR 012: NeMo Guardrails for input, code for tool and output rules

Status: Accepted · 10 Nov 2026

## Context

The app reads untrusted text (user messages, news, filings) and can change state (orders). It must resist misuse and must not present invented numbers or personal advice.

## Options considered

| Option | For | Against |
|---|---|---|
| A guardrails framework for everything | One tool, quick coverage of generic risks. | Business rules become model judgements. Adds latency and cost. |
| Custom code for everything | Exact, fast, fully understood. | Rebuilds generic checks, such as jailbreak detection, that already exist. |
| Framework for generic risks, code for domain rules | Each tool does what it is good at. | Two mechanisms to explain. |

## Decision

| Layer | Checks | How |
|---|---|---|
| Input | Jailbreak and injection attempts, off-topic requests, personal data | NeMo Guardrails input rails |
| Tool | Least-privilege tool sets, argument validation, order limits, human approval | Plain code |
| Output | Numbers trace to tool results, claims are cited, research framing rather than advice | Plain code, plus the Compliance Critic |

## Consequences

- Rule checks are in from the start, because they are part of correctness. NeMo input rails arrive in Phase 6.
- Azure OpenAI's own content filter remains on underneath, as a base layer.
- Text from news and filings is always treated as data, never as instructions. A safety eval plants an instruction inside a news article and checks it is ignored.
- Input rails add a model call per message. We measure that latency and keep the rail set small.

## In short

"I used a framework where the problem is generic and code where the rule is specific to my domain. 'No order above the cash balance' is an if statement, not a model's opinion."
