# Python Coding Standards (for AI coding assistants)

Baseline for every project. Project-specific rules (frameworks, databases, AI patterns) live in that project's own add-on file.

**Golden rule:** production-grade structure, beginner-friendly code, no unnecessary complexity.

## 1. Tooling Defaults
- Python 3.13, pinned in `.python-version`.
- `uv` for dependencies and virtual envs; commit `uv.lock`.
- `src/<package>/` layout with `tests/` mirroring it; `pyproject.toml` and `README.md` at the root.
- Ruff for linting and formatting; line length 100; rules `E, F, I, B, UP, SIM`.
- Pyright in standard mode.
- pytest with pytest-asyncio; markers `unit` and `integration`.
- `pydantic-settings` for configuration; commit `.env.example`, never `.env`.

## 2. Readability
- Follow PEP 8; use descriptive names and type hints on every function signature.
- Prefer explicit, straightforward code over clever one-liners, magic, or deep nesting.
- Keep each function to one job.
- Write Google-style docstrings on public functions and classes; use comments to explain *why*, not *what*.
- Use the standard library unless a dependency clearly saves work.

## 3. Project Structure
- Separate API routes, business services, domain models, repositories, integrations, and configuration.
- Keep API handlers thin: parse input, call a service, return output.
- Keep business logic free of framework and provider imports.
- Dependencies point inward: routes -> services -> domain. No circular imports.
- Create a layer only when it has real code to hold. No empty placeholders.

## 4. Reuse & Extensibility
- Don't abstract until the same code appears three times.
- Prefer composition and dependency injection over inheritance; pass dependencies in, don't construct them inside.
- Use `Protocol` or `ABC` only when there are two real implementations, or a test fake needs one.
- Every component must be testable on its own, with its dependencies replaced.

## 5. Production Quality
- Validate all external input with Pydantic models.
- Catch specific exceptions; no bare `except`; never swallow errors silently.
- Log with the `logging` module, one logger per module; never `print`. Never log secrets or personal data.
- Never hardcode secrets or environment-specific values; read them from settings.
- Set a timeout on every external call; retries are bounded and use backoff.
- Use async for all I/O (HTTP, database, LLM calls). Never call blocking code inside an async function.
- Release resources with context managers.

## 6. Testing
- Test core logic, edge cases, and failure paths.
- Unit tests make no real network, database, or LLM calls; use fakes or mocks.
- Add integration tests at important boundaries (API, database, external services).
- Test behaviour, not implementation details.

## 7. How the Agent Works
- One concept per change. Keep each change small enough to review in one sitting.
- Make focused changes; no unrelated refactoring.
- Ask before adding a dependency.
- Before saying "done", run `make check`, which runs:
  - `uv run ruff format .`
  - `uv run ruff check .`
  - `uv run pyright`
  - `uv run pytest`
- End each change with a short summary: what changed, where it lives, how to run it.

## 8. Learning-Oriented Behaviour
- Show how professionals organise Python projects, but implement each part simply.
- Briefly explain each new layer, pattern, or non-obvious Python feature, and why it is needed.
- Show where new code belongs and how it connects to existing components.
