import pytest
import respx
from httpx import Response

from linbot.config import Settings
from linbot.model.base import ProviderError
from linbot.model.providers.anthropic_provider import build_anthropic_provider


def make_provider():
    settings = Settings(
        _env_file=None,
        provider="anthropic",
        anthropic_api_key="sk-ant-test",
        database_url="sqlite+aiosqlite://",
    )
    provider = build_anthropic_provider(settings)
    # No SDK retries in tests — errors should surface immediately.
    provider._client = provider._client.with_options(max_retries=0)
    return provider


def message_body(content, stop_reason="end_turn"):
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "claude-opus-4-8",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 20},
    }


@respx.mock
async def test_anthropic_success_extracts_text_blocks():
    route = respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=Response(
            200,
            json=message_body(
                [
                    {"type": "thinking", "thinking": "", "signature": "sig"},
                    {"type": "text", "text": "A hash map uses a hash function."},
                ]
            ),
        )
    )
    provider = make_provider()
    answer = await provider.generate_answer("How does a hash map work?")
    await provider.aclose()

    assert answer.text == "A hash map uses a hash function."
    assert answer.model_id == "claude-opus-4-8"
    assert answer.provider == "anthropic"

    request = route.calls.last.request
    assert request.headers["x-api-key"] == "sk-ant-test"
    assert "anthropic-version" in request.headers
    import json

    body = json.loads(request.content)
    assert body["thinking"] == {"type": "adaptive"}
    assert body["system"]  # TA system prompt present
    assert body["messages"] == [{"role": "user", "content": "How does a hash map work?"}]


@respx.mock
async def test_anthropic_refusal_becomes_provider_error():
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=Response(200, json=message_body([], stop_reason="refusal"))
    )
    provider = make_provider()
    with pytest.raises(ProviderError, match="refusal"):
        await provider.generate_answer("q")
    await provider.aclose()


@respx.mock
async def test_anthropic_http_error_becomes_provider_error():
    error_body = {"type": "error", "error": {"type": "api_error", "message": "boom"}}
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=Response(500, json=error_body)
    )
    provider = make_provider()
    with pytest.raises(ProviderError, match="500"):
        await provider.generate_answer("q")
    await provider.aclose()
