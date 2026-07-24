import random

import pytest

from linbot.model.base import ProviderError
from linbot.model.providers.fake import FakeProvider
from linbot.model.router import ModelRouter


async def test_no_candidate_always_uses_primary():
    primary = FakeProvider()
    router = ModelRouter(primary=primary)
    for _ in range(10):
        answer = await router.answer("q")
    assert primary.calls == 10
    assert answer.fallback_used is False


async def test_canary_split_is_roughly_proportional():
    primary, candidate = FakeProvider(), FakeProvider()
    router = ModelRouter(
        primary=primary,
        candidate=candidate,
        canary_percent=20,
        rng=random.Random(42),
    )
    for _ in range(1000):
        await router.answer("q")
    share = candidate.calls / 1000 * 100
    assert 15 < share < 25, f"canary share was {share}%"


async def test_fallback_answers_when_primary_fails():
    fallback = FakeProvider()
    router = ModelRouter(primary=FakeProvider(fail=True), fallback=fallback)
    answer = await router.answer("q")
    assert answer.fallback_used is True
    assert fallback.calls == 1


async def test_no_fallback_propagates_error():
    router = ModelRouter(primary=FakeProvider(fail=True))
    with pytest.raises(ProviderError):
        await router.answer("q")


async def test_failing_candidate_falls_back_to_baseline():
    fallback = FakeProvider()
    router = ModelRouter(
        primary=FakeProvider(),
        candidate=FakeProvider(fail=True),
        canary_percent=100,
        fallback=fallback,
        rng=random.Random(1),
    )
    answer = await router.answer("q")
    assert answer.fallback_used is True
    assert fallback.calls == 1
