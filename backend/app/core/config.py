"""Application settings.

Every value arrives from the environment. Nothing is hardcoded, and no secret has a
usable default -- a missing secret must fail loudly at startup rather than silently
running with a placeholder.
"""

import json
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Environment = Literal["local", "ci", "staging", "production"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # -- Application ---------------------------------------------------------
    environment: Environment = "local"
    project_name: str = "VisitNote AI"
    api_v1_prefix: str = "/api/v1"
    log_level: str = "INFO"

    # -- Data ----------------------------------------------------------------
    database_url: PostgresDsn
    redis_url: RedisDsn
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10

    # -- Security ------------------------------------------------------------
    # Phase 2 consumes these; declared now so configuration is complete from the start.
    jwt_secret: str = Field(min_length=32)
    jwt_algorithm: str = "HS256"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 60 * 60 * 24 * 30

    # NoDecode is required, not stylistic. pydantic-settings JSON-decodes complex
    # types inside the environment source, before any field validator runs, so a
    # plain comma-separated value raises a parse error the validator never sees.
    # NoDecode hands the raw string through to `_split_csv` below.
    cors_origins: Annotated[list[str], NoDecode] = Field(default_factory=list)
    trusted_hosts: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["*"]
    )

    # -- Providers -----------------------------------------------------------
    # Optional until phase 4. Model identifiers live here and in note_templates,
    # never in pipeline code -- model lineups move faster than source does.
    llm_provider: str = "anthropic"
    llm_model_id: str = "claude-sonnet-5"
    anthropic_api_key: str | None = None

    transcription_provider: str = "deepgram"
    transcription_model_id: str = "nova-3"
    deepgram_api_key: str | None = None

    # -- Observability -------------------------------------------------------
    sentry_dsn: str | None = None
    langfuse_enabled: bool = False
    langfuse_host: str | None = None
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    # Content redaction defaults ON. Production must never send transcript or note
    # text to a tracing backend; see the observability section of the README.
    langfuse_redact_content: bool = True

    @field_validator("cors_origins", "trusted_hosts", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Accept a JSON list or a comma-separated string from the environment.

        Comma-separated is what a person writes in a .env file and what most
        deployment consoles produce; JSON is what a config-management tool emits.
        Both must work.
        """
        if isinstance(value, str):
            text = value.strip()
            if text.startswith("["):
                return json.loads(text)
            return [item.strip() for item in text.split(",") if item.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def sqlalchemy_url(self) -> str:
        """SQLAlchemy needs the asyncpg driver spelled out in the scheme."""
        url = str(self.database_url)
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url


@lru_cache
def get_settings() -> Settings:
    """Cached so the environment is read once per process."""
    return Settings()
