"""Echo stub (build-sequence step 3): proves every layer except the model.

If a request reaches this and comes back as JSON, the server↔model wiring works
without spending a token. Also the workhorse of the test suite.
"""

from __future__ import annotations

from linbot.model.base import Answer, ProviderError


class FakeProvider:
    name = "fake"

    def __init__(self, fail: bool = False) -> None:
        self.fail = fail
        self.calls = 0

    async def generate_answer(self, question: str) -> Answer:
        self.calls += 1
        if self.fail:
            raise ProviderError("fake provider configured to fail")
        return Answer(
            text=f"[fake] You asked: {question}",
            model_id="fake-echo",
            provider=self.name,
            latency_ms=0,
        )
