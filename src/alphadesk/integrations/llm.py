"""The model factory: the only place that knows which LLM provider is in use (ADR 014).

Agents ask for a tier ("small" or "large"), never for a provider or a model name.
Switching provider or model is a settings change, not a code change.
"""

from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from alphadesk.config.settings import Settings

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
        model = (
            settings.azure_openai_deployment_small
            if tier == "small"
            else settings.azure_openai_deployment_large
        )
    else:
        base_url = None  # None means OpenAI's own API
        api_key = settings.openai_api_key
        model = settings.openai_model_small if tier == "small" else settings.openai_model_large

    return ChatOpenAI(
        model=model or "",
        base_url=base_url,
        api_key=api_key,
        timeout=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )
