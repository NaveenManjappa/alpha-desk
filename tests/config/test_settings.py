"""Tests for the settings module."""

import pytest
from pydantic import ValidationError

from alphadesk.config.settings import Settings


@pytest.mark.unit
def test_defaults_load_without_any_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ALPHADESK_ENVIRONMENT", raising=False)
    monkeypatch.delenv("ALPHADESK_LOG_LEVEL", raising=False)

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.environment == "dev"
    assert settings.log_level == "INFO"


@pytest.mark.unit
def test_environment_variable_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHADESK_LOG_LEVEL", "DEBUG")

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.log_level == "DEBUG"


@pytest.mark.unit
def test_invalid_value_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHADESK_ENVIRONMENT", "staging")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
