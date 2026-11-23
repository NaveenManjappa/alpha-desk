.PHONY: check eval run setup-db web web-check

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

# Create the checkpoint and conversation tables in Postgres. Run it again after an update. Start it first: docker compose up -d
setup-db:
	uv run python scripts/setup_db.py

# Start the web app on http://localhost:4200, reloading when code changes. It sends API
# calls on to http://localhost:8000, so start the API too: make run
web: web/node_modules/.package-lock.json
	cd web && npm start

# Frontend lint, unit tests and a production build. Run before saying "done" on a web change.
web-check: web/node_modules/.package-lock.json
	cd web && npm run lint
	cd web && npm test -- --no-watch --no-progress
	cd web && npm run build

# Install the web app's packages, on first use and whenever package-lock.json changes. npm
# writes this hidden file into node_modules, so its age says when the last install was.
web/node_modules/.package-lock.json: web/package-lock.json
	cd web && npm ci
	touch $@
