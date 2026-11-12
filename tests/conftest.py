"""Shared test fixtures."""

import os

import pytest


@pytest.fixture(autouse=True)
def _isolate_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove ALPHADESK_* variables from the real shell so every test starts from a clean slate."""
    for name in list(os.environ):
        if name.startswith("ALPHADESK_"):
            monkeypatch.delenv(name)
