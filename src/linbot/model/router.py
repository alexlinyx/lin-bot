"""Router over providers: canary traffic split + fallback (ROADMAP §9).

With no candidate and no fallback this degenerates to "call the primary", so
pass one and the phased rollout share one code path. The split is a weighted
random choice per request — the simplest thing that works; stickiness or
per-client bucketing can come later if evaluation needs it.
"""

from __future__ import annotations

import random
from dataclasses import replace

from linbot.model.base import Answer, Provider, ProviderError


class ModelRouter:
    def __init__(
        self,
        primary: Provider,
        candidate: Provider | None = None,
        canary_percent: float = 0.0,
        fallback: Provider | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.primary = primary
        self.candidate = candidate
        self.canary_percent = canary_percent
        self.fallback = fallback
        self._rng = rng or random.Random()

    def _choose(self) -> Provider:
        if self.candidate is not None and self._rng.uniform(0, 100) < self.canary_percent:
            return self.candidate
        return self.primary

    async def answer(self, question: str, context: list[str] | None = None) -> Answer:
        chosen = self._choose()
        try:
            return await chosen.generate_answer(question, context)
        except ProviderError:
            if self.fallback is None or self.fallback is chosen:
                raise
            # A cold or failing primary degrades to a known-good provider,
            # not to an error in the student's face (ROADMAP §12).
            result = await self.fallback.generate_answer(question, context)
            return replace(result, fallback_used=True)
