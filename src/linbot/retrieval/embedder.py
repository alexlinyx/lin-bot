"""Embedding clients.

Voyage AI is the embeddings provider (Anthropic's recommended partner; Claude
itself has no embeddings endpoint). Same failure philosophy as the model
providers: everything becomes a RetrievalError the caller can handle cleanly.
"""

from __future__ import annotations

import asyncio
import hashlib
import math

import httpx


class RetrievalError(Exception):
    """Embedding or retrieval failure."""


class VoyageEmbedder:
    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_seconds: float = 30.0,
        max_retries_429: int = 0,
    ) -> None:
        # Retries suit batch ingestion; the interactive query path keeps the
        # default 0 so a rate-limited embedder degrades to an un-grounded
        # answer instantly instead of stalling the student.
        self.max_retries_429 = max_retries_429
        self.model = model
        self._client = httpx.AsyncClient(
            base_url="https://api.voyageai.com/v1",
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout_seconds,
        )

    async def embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        """input_type is "document" for ingestion, "query" for questions —
        Voyage prepends different instructions to each, improving retrieval.

        429s are retried with backoff: Voyage's free tier has a tight
        requests-per-minute cap, which batch ingestion can exceed.
        """
        attempts = 0
        try:
            while True:
                try:
                    response = await self._client.post(
                        "/embeddings",
                        json={"input": texts, "model": self.model, "input_type": input_type},
                    )
                    response.raise_for_status()
                    data = response.json()["data"]
                    return [item["embedding"] for item in data]
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 429 and attempts < self.max_retries_429:
                        attempts += 1
                        delay = float(exc.response.headers.get("retry-after", 21 * attempts))
                        await asyncio.sleep(delay)
                        continue
                    raise RetrievalError(
                        f"voyage returned HTTP {exc.response.status_code}"
                    ) from exc
        except httpx.HTTPError as exc:
            raise RetrievalError(f"voyage request failed: {type(exc).__name__}") from exc
        except (KeyError, IndexError, TypeError) as exc:
            raise RetrievalError("voyage returned an unexpected response shape") from exc

    async def aclose(self) -> None:
        await self._client.aclose()


class FakeEmbedder:
    """Deterministic embeddings for tests: direction derived from word hashes,
    so texts sharing words are more similar — enough to test ranking."""

    def __init__(self, dim: int = 32) -> None:
        self.dim = dim

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for word in text.lower().split():
            digest = hashlib.sha256(word.encode()).digest()
            for i in range(self.dim):
                vector[i] += (digest[i % len(digest)] - 128) / 128
        norm = math.sqrt(sum(v * v for v in vector)) or 1.0
        return [v / norm for v in vector]

    async def embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        return [self._embed_one(t) for t in texts]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)
