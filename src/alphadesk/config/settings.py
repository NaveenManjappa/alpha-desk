"""Application settings, loaded from environment variables and an optional `.env` file."""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


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


@lru_cache
def get_settings() -> Settings:
    """Return the shared settings instance.

    Cached so the environment is read once. Tests can call `get_settings.cache_clear()`
    to pick up changed environment variables.
    """
    return Settings()
