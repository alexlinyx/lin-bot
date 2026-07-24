"""The model seam: the one interface the rest of the app sees.

Everything provider-specific lives behind `Provider.generate_answer`. The server
layer never learns which model answered — it gets an `Answer` back, and the
attribution fields exist so the request log can record who produced it (ROADMAP §9).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


class ProviderError(Exception):
    """Any provider failure (network, timeout, bad response). Maps to HTTP 502."""


@dataclass
class Answer:
    text: str
    model_id: str
    provider: str
    latency_ms: int
    fallback_used: bool = False


class Provider(Protocol):
    name: str

    async def generate_answer(self, question: str, context: list[str] | None = None) -> Answer: ...
