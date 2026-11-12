"""Shared test fixtures."""

import os
from collections.abc import Iterator

import pytest


@pytest.fixture(scope="session", autouse=True)
def _tracing_off() -> Iterator[None]:
    """Make sure no unit test sends a trace to LangSmith.

    Removes every LANGSMITH_* and LANGCHAIN_* variable the shell may have set (including
    any API key), then sets tracing to "false". Session scope, because LangSmith caches
    these variables the first time it reads them, so they must be right from the start.
    """
    with pytest.MonkeyPatch.context() as patch:
        for name in list(os.environ):
            if name.startswith(("LANGSMITH_", "LANGCHAIN_")):
                patch.delenv(name)
        patch.setenv("LANGSMITH_TRACING", "false")
        yield


@pytest.fixture(autouse=True)
def _isolate_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove ALPHADESK_* variables from the real shell so every test starts from a clean slate."""
    for name in list(os.environ):
        if name.startswith("ALPHADESK_"):
            monkeypatch.delenv(name)
