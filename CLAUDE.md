# AlphaDesk

An AI investment research desk for US-listed companies, with a paper-trading portfolio. Built in phases. See `docs/architecture.md` for the design and `docs/adr/` for the decisions.

## Rules to follow

@CodingStandards.md
@docs/project-rules.md

## How we work

- Work is done one slice at a time, from the current phase spec in `docs/phases/`.
- Build only the slice you are asked for. Do not start the next slice.
- If a slice is unclear or conflicts with the architecture, stop and ask.

## Commands

- `make check` runs format, lint, type-check and unit tests. Run it before saying "done".
- `make eval` runs the eval suite. It calls a real LLM and costs tokens. Run it only when asked.
- `make run` starts the API locally.
