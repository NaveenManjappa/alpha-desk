"""Tests for the model factory. Building a model makes no network call."""

import pytest
from langchain_openai import ChatOpenAI

from alphadesk.config.settings import Settings
from alphadesk.domain.usage import ModelPrice
from alphadesk.integrations.llm import ModelTier, get_chat_model, get_model_name, get_model_price


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


@pytest.mark.unit
@pytest.mark.parametrize(
    "settings", [_openai_settings(), _azure_settings()], ids=["openai", "azure"]
)
def test_streamed_calls_report_token_usage_on_both_providers(settings: Settings) -> None:
    # LangChain turns this on by itself only for OpenAI's own URL, not for Azure's.
    model = get_chat_model("small", settings)

    assert isinstance(model, ChatOpenAI)
    assert model.stream_usage is True


@pytest.mark.unit
def test_each_tier_has_its_own_price_from_settings() -> None:
    settings = Settings(
        _env_file=None,  # pyright: ignore[reportCallIssue]
        openai_api_key="test-key",  # pyright: ignore[reportArgumentType]
        llm_price_small_input_per_million=0.25,
        llm_price_small_output_per_million=2.0,
        llm_price_large_input_per_million=1.25,
        llm_price_large_output_per_million=10.0,
    )

    assert get_model_price("small", settings) == ModelPrice(
        input_usd_per_million=0.25, output_usd_per_million=2.0
    )
    assert get_model_price("large", settings) == ModelPrice(
        input_usd_per_million=1.25, output_usd_per_million=10.0
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("settings", "tier", "expected"),
    [
        (_openai_settings(), "small", "small-model"),
        (_openai_settings(), "large", "large-model"),
        (_azure_settings(), "small", "small-deployment"),
        (_azure_settings(), "large", "large-deployment"),
    ],
)
def test_model_name_matches_the_model_the_factory_builds(
    settings: Settings, tier: ModelTier, expected: str
) -> None:
    model = get_chat_model(tier, settings)
    assert isinstance(model, ChatOpenAI)
    assert get_model_name(tier, settings) == expected == model.model_name
