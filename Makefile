.PHONY: check eval run setup-db

# Format, lint, type-check and unit tests. Run before saying "done".
check:
	uv run ruff format .
	uv run ruff check .
	uv run pyright
	uv run pytest

# Evals call a real LLM, Finnhub and SEC EDGAR, and cost tokens. Run only when asked.
# Prints a pass or fail per question and an overall score, and saves the results to
# evals/results/. Each case takes about a minute (agent calls, then three judge calls),
# so -v names each case as it starts and live INFO logs show the calls as they happen.
# --tb=line keeps failures to one line each; the summary at the end has the details.
eval:
	uv run pytest evals -m eval -v --tb=line -o log_cli=true --log-cli-level=INFO \
		--log-cli-format="%(asctime)s %(levelname)s %(name)s: %(message)s" \
		--log-cli-date-format="%H:%M:%S"

# Start the API on http://localhost:8000, reloading when code changes.
# With ALPHADESK_CHECKPOINTER=postgres, start Postgres first: docker compose up -d
run:
	uv run uvicorn alphadesk.api.app:create_app --factory --reload --port 8000

# Create the checkpoint tables in Postgres. Start it first: docker compose up -d
setup-db:
	uv run python scripts/setup_db.py
