"""The model factory: the only place that knows which LLM provider is in use (ADR 014).

Agents ask for a tier ("small" or "large"), never for a provider or a model name.
Switching provider or model is a settings change, not a code change.
"""

from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from alphadesk.config.settings import Settings
from alphadesk.domain.usage import ModelPrice

ModelTier = Literal["small", "large"]


def get_chat_model(tier: ModelTier, settings: Settings) -> BaseChatModel:
    """Build the chat model for a tier, using the provider chosen in settings.

    Both providers use `ChatOpenAI`. Azure OpenAI's v1 API speaks the same protocol as
    OpenAI, so only the address, the key and the model name change. On Azure the
    "model" is the name of a deployment you created in your Azure resource.

    Args:
        tier: "small" for cheap routing and extraction, "large" for analysis and critique.
        settings: Application settings. Passed in so tests can supply their own.

    Returns:
        A LangChain chat model. Creating it makes no network call.
    """
    base_url: str | None
    api_key: SecretStr | None
    if settings.llm_provider == "azure_openai":
        endpoint = settings.azure_openai_endpoint or ""
        base_url = endpoint.rstrip("/") + "/openai/v1/"
        api_key = settings.azure_openai_api_key
    else:
        base_url = None  # None means OpenAI's own API
        api_key = settings.openai_api_key

    return ChatOpenAI(
        model=get_model_name(tier, settings),
        base_url=base_url,
        api_key=api_key,
        timeout=settings.llm_timeout_seconds,
        # The OpenAI SDK retries connection errors, 408, 409, 429 and 5xx, with
        # exponential backoff. It does not retry a bad request or a rejected key.
        max_retries=settings.llm_max_retries,
        # Ask for token counts on streamed replies too. LangChain turns this on by
        # itself only for OpenAI's own URL, so without it Azure runs would report zero.
        stream_usage=True,
    )


def get_model_name(tier: ModelTier, settings: Settings) -> str:
    """The model a tier runs on: an OpenAI model name, or an Azure deployment name.

    The one place that maps a tier to its setting. `get_chat_model` uses it, and so does
    anything that reports which model ran, such as the eval results, so the two agree.

    Returns:
        The name, or "" if the setting is missing. The settings validator rejects a
        missing name at startup, so "" only appears with hand-built settings in tests.
    """
    if settings.llm_provider == "azure_openai":
        name = (
            settings.azure_openai_deployment_small
            if tier == "small"
            else settings.azure_openai_deployment_large
        )
    else:
        name = settings.openai_model_small if tier == "small" else settings.openai_model_large
    return name or ""


def get_model_price(tier: ModelTier, settings: Settings) -> ModelPrice:
    """The configured price of a tier's model, for the cost estimate.

    By tier, like `get_chat_model`, so it works the same whichever provider and model
    name the tier points at.
    """
    if tier == "small":
        return ModelPrice(
            input_usd_per_million=settings.llm_price_small_input_per_million,
            output_usd_per_million=settings.llm_price_small_output_per_million,
        )
    return ModelPrice(
        input_usd_per_million=settings.llm_price_large_input_per_million,
        output_usd_per_million=settings.llm_price_large_output_per_million,
    )
