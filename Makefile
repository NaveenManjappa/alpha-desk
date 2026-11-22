.PHONY: check eval run setup-db

# Format, lint, type-check and unit tests. Run before saying "done".
check:
	uv run ruff format .
	uv run ruff check .
	uv run pyright
	uv run pytest

# Evals call a real LLM and cost tokens. Run only when asked.
eval:
	uv run pytest -m eval

# Start the API on http://localhost:8000, reloading when code changes.
# With ALPHADESK_CHECKPOINTER=postgres, start Postgres first: docker compose up -d
run:
	uv run uvicorn alphadesk.api.app:create_app --factory --reload --port 8000

# Create the checkpoint tables in Postgres. Start it first: docker compose up -d
setup-db:
	uv run python scripts/setup_db.py
