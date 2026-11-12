"""Tests for the settings module."""

import pytest
from pydantic import ValidationError

from alphadesk.config.settings import Settings


@pytest.mark.unit
def test_defaults_load_with_only_the_openai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHADESK_OPENAI_API_KEY", "test-key")

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.environment == "dev"
    assert settings.log_level == "INFO"
    assert settings.llm_provider == "openai"


@pytest.mark.unit
def test_environment_variable_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHADESK_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("ALPHADESK_LOG_LEVEL", "DEBUG")

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.log_level == "DEBUG"


@pytest.mark.unit
def test_invalid_value_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHADESK_OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("ALPHADESK_ENVIRONMENT", "staging")

    with pytest.raises(ValidationError):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


@pytest.mark.unit
def test_missing_openai_key_names_the_setting() -> None:
    with pytest.raises(ValidationError, match="ALPHADESK_OPENAI_API_KEY"):
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]


@pytest.mark.unit
def test_azure_settings_are_not_needed_for_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHADESK_OPENAI_API_KEY", "test-key")

    settings = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.azure_openai_endpoint is None


@pytest.mark.unit
def test_missing_azure_settings_are_all_named(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ALPHADESK_LLM_PROVIDER", "azure_openai")
    monkeypatch.setenv("ALPHADESK_AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com/")

    with pytest.raises(ValidationError) as error:
        Settings(_env_file=None)  # pyright: ignore[reportCallIssue]

    message = str(error.value)
    assert "ALPHADESK_AZURE_OPENAI_API_KEY" in message
    assert "ALPHADESK_AZURE_OPENAI_DEPLOYMENT_SMALL" in message
    assert "ALPHADESK_AZURE_OPENAI_ENDPOINT" not in message
