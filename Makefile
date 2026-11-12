.PHONY: check eval run

# Format, lint, type-check and unit tests. Run before saying "done".
check:
	uv run ruff format .
	uv run ruff check .
	uv run pyright
	uv run pytest

# Evals call a real LLM and cost tokens. Run only when asked.
eval:
	uv run pytest -m eval

# The API arrives in Slice 11; until then there is nothing to start.
run:
	@echo "No API yet: 'make run' is wired up in Slice 11."
	@exit 1
