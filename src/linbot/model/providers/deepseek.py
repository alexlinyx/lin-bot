"""DeepSeek direct API — the pass-one primary (ROADMAP §4)."""

from __future__ import annotations

from linbot.config import Settings
from linbot.model.providers.openai_compat import OpenAICompatChatProvider


def build_deepseek_provider(settings: Settings) -> OpenAICompatChatProvider:
    assert settings.deepseek_api_key is not None  # enforced by config validation
    return OpenAICompatChatProvider(
        name="deepseek",
        base_url=settings.deepseek_base_url.rstrip("/"),
        api_key=settings.deepseek_api_key,
        model=settings.model_name,
        timeout_seconds=settings.request_timeout_seconds,
    )
