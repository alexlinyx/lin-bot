import pytest
import respx
from httpx import Response

from linbot.config import Settings
from linbot.model.base import ProviderError
from linbot.model.providers.deepseek import build_deepseek_provider


def make_provider():
    settings = Settings(
        _env_file=None,
        provider="deepseek",
        deepseek_api_key="test-key",
        model_name="deepseek-chat",
        database_url="sqlite+aiosqlite://",
    )
    return build_deepseek_provider(settings)


@respx.mock
async def test_deepseek_success():
    route = respx.post("https://api.deepseek.com/chat/completions").mock(
        return_value=Response(
            200,
            json={
                "model": "deepseek-chat",
                "choices": [{"message": {"role": "assistant", "content": "An answer."}}],
            },
        )
    )
    provider = make_provider()
    answer = await provider.generate_answer("What is Big-O?")
    await provider.aclose()

    assert answer.text == "An answer."
    assert answer.model_id == "deepseek-chat"
    assert answer.provider == "deepseek"

    request = route.calls.last.request
    assert request.headers["authorization"] == "Bearer test-key"
    import json

    body = json.loads(request.content)
    assert body["messages"][0]["role"] == "system"
    assert body["messages"][1] == {"role": "user", "content": "What is Big-O?"}


@respx.mock
async def test_deepseek_http_error_becomes_provider_error():
    respx.post("https://api.deepseek.com/chat/completions").mock(return_value=Response(500))
    provider = make_provider()
    with pytest.raises(ProviderError, match="502|500"):
        await provider.generate_answer("q")
    await provider.aclose()


@respx.mock
async def test_deepseek_malformed_body_becomes_provider_error():
    respx.post("https://api.deepseek.com/chat/completions").mock(
        return_value=Response(200, json={"unexpected": True})
    )
    provider = make_provider()
    with pytest.raises(ProviderError, match="unexpected response shape"):
        await provider.generate_answer("q")
    await provider.aclose()
