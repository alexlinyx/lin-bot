"""Anthropic Claude via the official SDK.

Unlike DeepSeek and HF TGI/vLLM, Anthropic's Messages API is not
OpenAI-compatible (different endpoint, auth header, and response shape), so
this provider uses the official `anthropic` SDK rather than the shared
OpenAI-style client. On models that support it (Claude 4.6+), adaptive
thinking is enabled — Claude decides per question how much to reason
before answering.
"""

from __future__ import annotations

import time

import anthropic

from linbot.config import Settings
from linbot.model.base import Answer, ProviderError
from linbot.model.prompts import SYSTEM_PROMPT, build_user_message


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str, timeout_seconds: float) -> None:
        self.model = model
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout_seconds)

    async def generate_answer(self, question: str, context: list[str] | None = None) -> Answer:
        # Adaptive thinking exists on Claude 4.6+ models only; sending it to
        # Haiku 4.5 (or older) returns a 400, so it's applied conditionally.
        extra: dict = {}
        if not self.model.startswith(("claude-haiku", "claude-sonnet-4-5")):
            extra["thinking"] = {"type": "adaptive"}

        start = time.monotonic()
        try:
            response = await self._client.messages.create(
                model=self.model,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": build_user_message(question, context)}],
                **extra,
            )
        except anthropic.APIStatusError as exc:
            raise ProviderError(f"anthropic returned HTTP {exc.status_code}") from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError("anthropic request failed: connection error") from exc

        # Safety classifiers can decline a request with a successful HTTP 200
        # and stop_reason "refusal" — treat it as a provider failure so the
        # router's fallback path (if configured) can answer instead.
        if response.stop_reason == "refusal":
            raise ProviderError("anthropic declined the request (refusal)")

        text = "".join(block.text for block in response.content if block.type == "text")
        if not text:
            raise ProviderError("anthropic returned no text content")

        latency_ms = int((time.monotonic() - start) * 1000)
        return Answer(text=text, model_id=response.model, provider=self.name, latency_ms=latency_ms)

    async def aclose(self) -> None:
        await self._client.close()


def build_anthropic_provider(settings: Settings) -> AnthropicProvider:
    assert settings.anthropic_api_key is not None  # enforced by config validation
    return AnthropicProvider(
        api_key=settings.anthropic_api_key,
        model=settings.anthropic_model_name,
        timeout_seconds=settings.request_timeout_seconds,
    )
