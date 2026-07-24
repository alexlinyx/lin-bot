"""Anthropic Claude via the official SDK.

Unlike DeepSeek and HF TGI/vLLM, Anthropic's Messages API is not
OpenAI-compatible (different endpoint, auth header, and response shape), so
this provider uses the official `anthropic` SDK rather than the shared
OpenAI-style client. Adaptive thinking is enabled — Claude decides per
question how much to reason before answering.
"""

from __future__ import annotations

import time

import anthropic

from linbot.config import Settings
from linbot.model.base import Answer, ProviderError
from linbot.model.prompts import SYSTEM_PROMPT


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str, model: str, timeout_seconds: float) -> None:
        self.model = model
        self._client = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout_seconds)

    async def generate_answer(self, question: str) -> Answer:
        start = time.monotonic()
        try:
            response = await self._client.messages.create(
                model=self.model,
                max_tokens=16000,
                system=SYSTEM_PROMPT,
                thinking={"type": "adaptive"},
                messages=[{"role": "user", "content": question}],
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
