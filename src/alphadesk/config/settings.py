"""Application settings, loaded from environment variables and an optional `.env` file."""

from functools import lru_cache
from typing import Literal, Self

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LlmProvider = Literal["openai", "azure_openai"]


class Settings(BaseSettings):
    """All configuration for AlphaDesk.

    Each field is read from an environment variable named `ALPHADESK_<FIELD>`,
    for example `ALPHADESK_LOG_LEVEL`. Values in the real environment win over `.env`.
    """

    model_config = SettingsConfigDict(
        env_prefix="ALPHADESK_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["dev", "test", "prod"] = "dev"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"

    # --- LLM provider (ADR 014) ---
    llm_provider: LlmProvider = "openai"
    llm_timeout_seconds: float = 60.0
    llm_max_retries: int = 2

    # OpenAI. Model names per tier; both tiers may point at the same model.
    openai_api_key: SecretStr | None = None
    openai_model_small: str = "gpt-5-mini"
    openai_model_large: str = "gpt-5-mini"

    # Azure OpenAI, called through its v1 API, which needs no API version.
    # Read only when llm_provider is "azure_openai".
    # On Azure you call a deployment you created, not a model name, so each tier names one.
    azure_openai_endpoint: str | None = None
    azure_openai_api_key: SecretStr | None = None
    azure_openai_deployment_small: str | None = None
    azure_openai_deployment_large: str | None = None

    # --- Tracing (ADR 008) ---
    # Off by default, so tests and fresh clones never send traces by accident.
    langsmith_tracing: bool = False
    langsmith_api_key: SecretStr | None = None
    langsmith_project: str = "alphadesk-dev"
    # Only needed outside LangSmith's US region, e.g. https://eu.api.smith.langchain.com
    langsmith_endpoint: str | None = None

    @model_validator(mode="after")
    def _require_tracing_settings(self) -> Self:
        """Tracing without a key would fail quietly in a background thread, so fail loudly here."""
        if self.langsmith_tracing and not self.langsmith_api_key:
            raise ValueError(
                "ALPHADESK_LANGSMITH_TRACING is true but ALPHADESK_LANGSMITH_API_KEY is missing. "
                "Set the key, or turn tracing off."
            )
        return self

    @model_validator(mode="after")
    def _require_provider_settings(self) -> Self:
        """Fail at startup, naming every missing setting, rather than on the first model call."""
        if self.llm_provider == "openai":
            required = {"openai_api_key": self.openai_api_key}
        else:
            required = {
                "azure_openai_endpoint": self.azure_openai_endpoint,
                "azure_openai_api_key": self.azure_openai_api_key,
                "azure_openai_deployment_small": self.azure_openai_deployment_small,
                "azure_openai_deployment_large": self.azure_openai_deployment_large,
            }
        missing = [f"ALPHADESK_{name.upper()}" for name, value in required.items() if not value]
        if missing:
            raise ValueError(
                f"Missing required setting(s) for llm_provider='{self.llm_provider}': "
                f"{', '.join(missing)}. Set them in the environment or in .env."
            )
        return self


@lru_cache
def get_settings() -> Settings:
    """Return the shared settings instance.

    Cached so the environment is read once. Tests can call `get_settings.cache_clear()`
    to pick up changed environment variables.
    """
    return Settings()
