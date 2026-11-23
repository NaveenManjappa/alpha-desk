# AlphaDesk

An AI investment research desk for US-listed companies, with a paper-trading portfolio.

Ask about a company and get a short, typed answer where every number has a source link. AlphaDesk is built in phases; see [docs/architecture.md](docs/architecture.md) for the full design.

> This is a research tool, not financial advice.

## Status

**Phase 1, Slice 0: project skeleton.** The project layout, tooling and settings are in place. The research agent, its tools and the API arrive in later slices of [the Phase 1 spec](docs/phases/phase-1-spec.md).

## Requirements

- [uv](https://docs.astral.sh/uv/). It installs Python 3.13 for you if you don't have it.
- `make`
- Git

Later slices also need Docker Desktop, an OpenAI API key, a LangSmith key and a Finnhub key. The Phase 1 spec lists them.

## Getting started

```bash
git clone <repo-url>
cd alpha-desk
cp .env.example .env   # then fill in real values
make check             # creates .venv, installs dependencies, runs all checks
```

`uv run` creates the virtual environment and installs everything from `uv.lock` on first use. There is no separate install step.

## Commands

| Command | What it does |
|---|---|
| `make check` | Formats, lints, type-checks and runs the unit tests. Run it before every commit. |
| `make eval` | Runs the golden-dataset evals against the real LLM, Finnhub and SEC EDGAR. It costs tokens. Prints a pass or fail per question and a score, and saves results to `evals/results/`. |
| `make run` | Starts the API on http://localhost:8000. Interactive docs at `/docs`. |
| `make setup-db` | Creates the checkpoint tables in Postgres. Safe to run again. |

`make check` runs these four commands in order and stops at the first failure:

```bash
uv run ruff format .   # code style
uv run ruff check .    # lint: likely bugs and outdated patterns
uv run pyright         # static type checking
uv run pytest          # unit tests (evals excluded)
```

## Local database

Conversation memory is saved in Postgres when `ALPHADESK_CHECKPOINTER=postgres` (the value in `.env.example`). Start the database and create its tables once:

```bash
docker compose up -d   # Postgres on localhost:5433; data kept in a Docker volume
make setup-db          # creates the `checkpoints` schema and tables
```

With `ALPHADESK_CHECKPOINTER=memory`, nothing needs Docker, but memory is lost when the program exits. Unit tests always use memory. To run the Postgres integration tests:

```bash
TEST_POSTGRES_URL=postgresql://alphadesk:alphadesk@localhost:5433/alphadesk uv run pytest -m integration
```

## Running the API

```bash
docker compose up -d   # only with ALPHADESK_CHECKPOINTER=postgres
make run               # http://localhost:8000, docs at http://localhost:8000/docs
```

`POST /chat` streams [Server-Sent Events](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events): `status` when a tool starts, `token` as model text arrives, then one `final` (with the `Answer`) or one `error`. Send the same `thread_id` again to continue the conversation. `-N` stops curl buffering the stream:

```bash
curl -N -X POST http://localhost:8000/chat \
  -H 'Content-Type: application/json' \
  -d '{"message": "What is Apple'\''s share price?", "thread_id": "demo"}'

curl -i http://localhost:8000/health   # 503 if Postgres is configured but unreachable
```

## Configuration

Settings are read from environment variables with the `ALPHADESK_` prefix, then from a local `.env` file. Real environment variables win. [.env.example](.env.example) lists every setting; copy it to `.env` and never commit `.env`.

| Variable | Default | Values |
|---|---|---|
| `ALPHADESK_ENVIRONMENT` | `dev` | `dev`, `test`, `prod` |
| `ALPHADESK_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |

Invalid values fail at startup with a message that names the setting.

## Project layout

```
alpha-desk/
  src/alphadesk/
    config/          # settings (pydantic-settings)
  tests/             # mirrors src/
  docs/
    architecture.md  # the design
    adr/             # architecture decision records
    phases/          # one spec per build phase
  pyproject.toml     # metadata, dependencies, tool config
  uv.lock            # pinned dependency versions
  Makefile           # check, eval, run
```

More folders (`api/`, `agents/`, `tools/`, `services/`, `integrations/` and others) are added as each slice needs them. [docs/project-rules.md](docs/project-rules.md) says what belongs in each.

## Contributing

Read these before writing code:

- [CodingStandards.md](CodingStandards.md): general Python standards.
- [docs/project-rules.md](docs/project-rules.md): rules specific to AlphaDesk, including the AI rules.
- [docs/adr/](docs/adr/): why the main decisions were made.

Work is done one slice at a time, with one commit per slice.
