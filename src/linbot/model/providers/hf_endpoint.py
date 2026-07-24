"""Self-hosted fine-tuned model on a HF Inference Endpoint (Phase 2+, ROADMAP §9).

TGI/vLLM endpoints expose an OpenAI-compatible /v1/chat/completions route, so
this is the same client pointed at a different URL — exactly the payoff of the
single model seam.
"""

from __future__ import annotations

from linbot.config import Settings
from linbot.model.providers.openai_compat import OpenAICompatChatProvider


def build_hf_provider(settings: Settings) -> OpenAICompatChatProvider:
    assert settings.hf_endpoint_url is not None and settings.hf_token is not None
    return OpenAICompatChatProvider(
        name="hf",
        base_url=settings.hf_endpoint_url.rstrip("/") + "/v1",
        api_key=settings.hf_token,
        model=settings.hf_model_name,
        timeout_seconds=settings.request_timeout_seconds,
    )
