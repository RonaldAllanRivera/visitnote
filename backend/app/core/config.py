"""Application settings.

Every value arrives from the environment. Nothing is hardcoded, and no secret has a
usable default -- a missing secret must fail loudly at startup rather than silently
running with a placeholder.
"""

import json
from decimal import Decimal
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

from app.llm.costs import ModelPrice

Environment = Literal["local", "ci", "staging", "production"]
# Mirrors the API's accepted effort levels. Typed rather than free-form so an
# invalid value is a startup failure, not a 400 on the first note of the day.
LLMEffort = Literal["low", "medium", "high", "xhigh", "max"]


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
    # Login throttling. The lockout is short and self-clearing on purpose: a
    # per-account lock is also a denial-of-service vector against any address an
    # attacker knows, so it must expire without an administrator in the loop.
    login_max_attempts: int = 5
    login_failure_window_seconds: int = 900
    login_lockout_seconds: int = 900

    # Object storage. Absent locally, where the fake provider is used instead.
    r2_bucket: str = "visitnote-dev"
    r2_endpoint_url: str | None = None
    # The address the *client* can reach, when it differs from the one the API uses.
    # Locally the API reaches MinIO at minio:9000 on the compose network while the
    # browser can only reach localhost:9000. A presigned URL is signed over the host
    # it will be sent to, so this has to be applied at signing time -- rewriting the
    # host afterwards invalidates the signature. Unset in production, where R2 is one
    # address for both.
    r2_public_endpoint_url: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: str | None = None
    # Short-lived by design: a leaked URL stops working quickly, and the client
    # requests a fresh one when resuming.
    presigned_url_ttl_seconds: int = 900

    # Google sign-in. Absent in local development, where the feature simply reports
    # itself unconfigured rather than failing in a confusing way.
    google_client_id: str | None = None

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
    # How hard the model works on a note. The primary cost lever, and configuration
    # rather than code for the same reason the model id is: it is tuned against eval
    # scores, and a tuning change must not require a deployment.
    llm_effort: LLMEffort = "medium"

    transcription_provider: str = "deepgram"
    transcription_model_id: str = "nova-3"
    deepgram_api_key: str | None = None
    # An additional layer before transcript text reaches the LLM. Off by default
    # because it also redacts clinically relevant detail -- ages, dates, and numbers
    # a note legitimately needs -- so it is a deployment decision, not a default.
    deepgram_redact_pii: bool = False

    # Published rates, in USD per million tokens, keyed by model id. Configuration
    # rather than code for the same reason the model id is: prices change, and a
    # price change must not require a deployment. A model absent from this map
    # records no cost at all rather than a misleading zero.
    llm_prices: dict[str, ModelPrice] = Field(
        default_factory=lambda: {
            "claude-sonnet-5": ModelPrice(
                input_usd_per_mtok=Decimal("2.00"), output_usd_per_mtok=Decimal("10.00")
            ),
            "claude-opus-5": ModelPrice(
                input_usd_per_mtok=Decimal("5.00"), output_usd_per_mtok=Decimal("25.00")
            ),
            "claude-haiku-4-5": ModelPrice(
                input_usd_per_mtok=Decimal("1.00"), output_usd_per_mtok=Decimal("5.00")
            ),
        }
    )
    # Deepgram prerecorded, per audio minute. Verify against current pricing for a
    # real deployment; it is here so that verifying it is a config change.
    transcription_usd_per_minute: Decimal = Decimal("0.0043")

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
