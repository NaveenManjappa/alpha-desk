"""Tests for the model factory. Building a model makes no network call."""

import pytest
from langchain_openai import ChatOpenAI

from alphadesk.config.settings import Settings
from alphadesk.integrations.llm import ModelTier, get_chat_model


def _openai_settings() -> Settings:
    return Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        openai_api_key="test-key",  # pyright: ignore[reportArgumentType]
        openai_model_small="small-model",
        openai_model_large="large-model",
    )


def _azure_settings() -> Settings:
    return Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        llm_provider="azure_openai",
        azure_openai_endpoint="https://example.openai.azure.com/",
        azure_openai_api_key="test-key",  # pyright: ignore[reportArgumentType]
        azure_openai_deployment_small="small-deployment",
        azure_openai_deployment_large="large-deployment",
    )


@pytest.mark.unit
@pytest.mark.parametrize(("tier", "expected"), [("small", "small-model"), ("large", "large-model")])
def test_openai_factory_picks_the_model_for_each_tier(tier: ModelTier, expected: str) -> None:
    model = get_chat_model(tier, _openai_settings())

    assert isinstance(model, ChatOpenAI)
    assert model.model_name == expected


@pytest.mark.unit
def test_openai_model_gets_timeout_and_bounded_retries() -> None:
    model = get_chat_model("small", _openai_settings())

    assert isinstance(model, ChatOpenAI)
    assert model.request_timeout == 60.0
    assert model.max_retries == 2


@pytest.mark.unit
@pytest.mark.parametrize(
    ("tier", "expected"), [("small", "small-deployment"), ("large", "large-deployment")]
)
def test_azure_provider_points_at_the_azure_v1_endpoint(tier: ModelTier, expected: str) -> None:
    model = get_chat_model(tier, _azure_settings())

    assert isinstance(model, ChatOpenAI)
    assert model.model_name == expected
    assert model.openai_api_base == "https://example.openai.azure.com/openai/v1/"


@pytest.mark.unit
def test_openai_provider_uses_openai_default_endpoint() -> None:
    model = get_chat_model("small", _openai_settings())

    assert isinstance(model, ChatOpenAI)
    assert model.openai_api_base is None
