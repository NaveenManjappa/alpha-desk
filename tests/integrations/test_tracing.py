"""Tests for switching LangSmith tracing on and off."""

import os

import pytest

from alphadesk.config.settings import Settings
from alphadesk.integrations.tracing import configure_tracing


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, openai_api_key="test-key", **overrides)  # pyright: ignore[reportCallIssue, reportArgumentType]


@pytest.mark.unit
def test_tracing_on_sets_the_langsmith_variables() -> None:
    environ: dict[str, str] = {}

    configure_tracing(_settings(langsmith_tracing=True, langsmith_api_key="ls-key"), environ)

    assert environ == {
        "LANGSMITH_TRACING": "true",
        "LANGSMITH_API_KEY": "ls-key",
        "LANGSMITH_PROJECT": "alphadesk-dev",
    }


@pytest.mark.unit
def test_endpoint_is_set_only_when_configured() -> None:
    environ: dict[str, str] = {}
    settings = _settings(
        langsmith_tracing=True,
        langsmith_api_key="ls-key",
        langsmith_endpoint="https://eu.api.smith.langchain.com",
    )

    configure_tracing(settings, environ)

    assert environ["LANGSMITH_ENDPOINT"] == "https://eu.api.smith.langchain.com"


@pytest.mark.unit
def test_tracing_off_overrides_the_shell_and_writes_no_key() -> None:
    environ = {"LANGSMITH_TRACING": "true"}  # as if the shell had switched it on

    configure_tracing(_settings(), environ)

    assert environ == {"LANGSMITH_TRACING": "false"}


@pytest.mark.unit
def test_unit_tests_run_with_tracing_off() -> None:
    # Set by the session fixture in conftest.py.
    assert os.environ["LANGSMITH_TRACING"] == "false"
    assert "LANGSMITH_API_KEY" not in os.environ
    assert "LANGCHAIN_TRACING_V2" not in os.environ
