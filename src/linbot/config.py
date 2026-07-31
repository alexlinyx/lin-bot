"""Configuration loaded from the environment at startup.

Nothing else in the app reads env vars directly. Validation happens here, once,
loudly: a server that boots without an API key and only finds out on the first
request fails confusingly under load. We refuse to boot instead.
"""

from __future__ import annotations

import sys
from typing import Literal

from pydantic import ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ProviderName = Literal["fake", "deepseek", "hf", "anthropic"]


def normalize_database_url(url: str) -> str:
    """Railway/Heroku hand out postgres:// or postgresql:// URLs; SQLAlchemy
    needs the driver spelled out to pick psycopg (v3). Shared with alembic."""
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Routing
    provider: ProviderName = "deepseek"
    canary_provider: ProviderName | None = None
    canary_percent: float = 0.0
    fallback_provider: ProviderName | None = None

    # DeepSeek direct (pass one primary)
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    model_name: str = "deepseek-chat"

    # Self-hosted fine-tuned model on HF Inference Endpoints (Phase 2+)
    hf_endpoint_url: str | None = None
    hf_token: str | None = None
    hf_model_name: str = "linbot-v1"

    # Anthropic Claude (alternative hosted provider for testing/comparison)
    anthropic_api_key: str | None = None
    anthropic_model_name: str = "claude-haiku-4-5"

    # Retrieval (RAG) over the course website. Optional: without a Voyage key
    # the app answers un-grounded; ingestion requires it.
    voyage_api_key: str | None = None
    voyage_model: str = "voyage-3.5-lite"
    rag_source_url: str = "https://alexlinyx.com/llms.txt"
    rag_top_k: int = 4
    rag_min_similarity: float = 0.3

    # Storage
    database_url: str

    # Guardrails
    rate_limit: int = 30
    rate_limit_window_seconds: int = 60
    max_question_chars: int = 4000
    request_timeout_seconds: float = 60.0

    # Access gate: when ACCESS_PASSWORD is set, every page and API route
    # requires a login session (only /login and /healthz stay open).
    # SESSION_SECRET signs the session cookie; it defaults to the password.
    access_password: str | None = None
    session_secret: str | None = None
    session_ttl_seconds: int = 2_592_000  # 30 days
    login_rate_limit: int = 10  # login attempts per client per minute

    # HTTP
    port: int = 8000

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, v: str) -> str:
        return normalize_database_url(v)

    @model_validator(mode="after")
    def _check_provider_requirements(self) -> Settings:
        if not 0 <= self.canary_percent <= 100:
            raise ValueError("CANARY_PERCENT must be between 0 and 100")
        if self.canary_percent > 0 and self.canary_provider is None:
            raise ValueError("CANARY_PERCENT is set but CANARY_PROVIDER is not")

        in_use = {self.provider, self.canary_provider, self.fallback_provider} - {None}
        if "deepseek" in in_use and not self.deepseek_api_key:
            raise ValueError("provider 'deepseek' is configured but DEEPSEEK_API_KEY is missing")
        if "hf" in in_use:
            if not self.hf_endpoint_url:
                raise ValueError("provider 'hf' is configured but HF_ENDPOINT_URL is missing")
            if not self.hf_token:
                raise ValueError("provider 'hf' is configured but HF_TOKEN is missing")
        if "anthropic" in in_use and not self.anthropic_api_key:
            raise ValueError("provider 'anthropic' is configured but ANTHROPIC_API_KEY is missing")
        return self


def load_settings() -> Settings:
    """Load settings or exit with a readable message — never a bare traceback."""
    try:
        return Settings()
    except ValidationError as exc:
        lines = ["LinBot cannot start: configuration is invalid.", ""]
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"]) or "settings"
            lines.append(f"  - {loc}: {err['msg']}")
        lines.append("")
        lines.append("Set the variables in your environment or .env (see .env.example).")
        print("\n".join(lines), file=sys.stderr)
        raise SystemExit(1) from exc
