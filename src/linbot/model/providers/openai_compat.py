"""Shared client for OpenAI-style chat-completions APIs.

Both DeepSeek's hosted API and HF Inference Endpoints (TGI/vLLM) speak this
format, so each concrete provider is just this class with different settings.
Every failure mode — network, timeout, HTTP error, malformed body — becomes a
ProviderError; callers never see a stack trace from inside a provider.
"""

from __future__ import annotations

import time

import httpx

from linbot.model.base import Answer, History, ProviderError
from linbot.model.prompts import SYSTEM_PROMPT, build_user_message


class OpenAICompatChatProvider:
    def __init__(
        self,
        name: str,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 60.0,
    ) -> None:
        self.name = name
        self.model = model
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_seconds,
        )

    async def generate_answer(
        self,
        question: str,
        context: list[str] | None = None,
        history: History | None = None,
    ) -> Answer:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                *(history or []),
                {"role": "user", "content": build_user_message(question, context)},
            ],
        }
        start = time.monotonic()
        try:
            response = await self._client.post("/chat/completions", json=payload)
            response.raise_for_status()
            body = response.json()
            text = body["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as exc:
            raise ProviderError(
                f"{self.name} returned HTTP {exc.response.status_code}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"{self.name} request failed: {type(exc).__name__}") from exc
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ProviderError(f"{self.name} returned an unexpected response shape") from exc

        latency_ms = int((time.monotonic() - start) * 1000)
        model_id = body.get("model", self.model)
        return Answer(text=text, model_id=model_id, provider=self.name, latency_ms=latency_ms)

    async def aclose(self) -> None:
        await self._client.aclose()
