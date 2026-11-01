"""M2 tests: LLM provider interfaces, adapters, factory and errors.

Everything runs offline:
- real adapters are exercised against ``httpx.MockTransport`` responses
  (real SSE parsing, real error paths, zero network);
- ``FakeLLMProvider`` covers what pipelines will consume in M4.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from types import SimpleNamespace

import httpx
import pytest

from app.core.llm import (
    ChatMessage,
    FakeLLMProvider,
    MissingAPIKeyError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
    UnsupportedProviderError,
    build_provider,
)
from app.core.llm.ollama import OllamaProvider
from app.core.llm.openrouter import OpenRouterProvider

# --------------------------------------------------------------------- #
# helpers                                                                #
# --------------------------------------------------------------------- #

CHAT = [
    ChatMessage(role="system", content="You answer from documents."),
    ChatMessage(role="user", content="What is the refund policy?"),
]


def sse_body(chunks: list[str]) -> bytes:
    """Craft an OpenAI-style SSE body with a final [DONE] sentinel."""
    lines: list[bytes] = []
    for i, chunk in enumerate(chunks):
        event = {"id": f"e{i}", "choices": [{"index": 0, "delta": {"content": chunk}}]}
        lines.append(f"data: {json.dumps(event)}".encode())
    lines.append(b"data: [DONE]")
    result = b""
    for line in lines:
        result += line + b"\n\n"
    return result


def make_handler(
    chunks: list[str],
    calls: list[httpx.Request] | None = None,
) -> Callable[[httpx.Request], httpx.Response]:
    """httpx handler that answers an SSE stream for the canned chunks."""

    def handler(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        return httpx.Response(
            200,
            content=sse_body(chunks),
            headers={"content-type": "text/event-stream"},
        )

    return handler


def raw_handler(body: bytes) -> Callable[[httpx.Request], httpx.Response]:
    """httpx handler answering an opaque raw body (error-path tests)."""

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"content-type": "text/event-stream"})

    return handler


def ollama_streaming(
    chunks: list[str],
    calls: list[httpx.Request] | None = None,
) -> OllamaProvider:
    """OllamaProvider over a mocked transport streaming *chunks*."""
    return OllamaProvider(
        base_url="http://test/v1",
        model="test-model",
        transport=httpx.MockTransport(make_handler(chunks, calls)),
    )


def ollama_raw(body: bytes) -> OllamaProvider:
    return OllamaProvider(base_url="http://test/v1", transport=httpx.MockTransport(raw_handler(body)))


def ollama_with(handler: Callable[[httpx.Request], httpx.Response]) -> OllamaProvider:
    """OllamaProvider over a bespoke mocked handler (full control)."""
    return OllamaProvider(base_url="http://test/v1", transport=httpx.MockTransport(handler))


# --------------------------------------------------------------------- #
# streaming + request shaping                                            #
# --------------------------------------------------------------------- #


def test_ollama_streams_in_order_and_hits_compatible_endpoint() -> None:
    calls: list[httpx.Request] = []
    provider = ollama_streaming(["Hel", "lo ", "world"], calls=calls)

    assert list(provider.stream_chat(CHAT)) == ["Hel", "lo ", "world"]

    request = calls[0]
    assert request.url.path == "/v1/chat/completions"
    payload = json.loads(request.read())
    assert payload["model"] == "test-model"
    assert payload["stream"] is True
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][1]["content"] == "What is the refund policy?"


def test_openrouter_wires_auth_and_required_headers() -> None:
    calls: list[httpx.Request] = []
    provider = OpenRouterProvider(
        base_url="https://test/api/v1",
        api_key="sk-offline-test",
        model="meta-llama/llama-3.3-70b-instruct:free",
        transport=httpx.MockTransport(make_handler(["Hi"], calls)),
    )

    assert list(provider.stream_chat(CHAT)) == ["Hi"]
    request = calls[0]
    assert request.headers["Authorization"] == "Bearer sk-offline-test"
    assert request.headers["X-Title"] == "KnowSphere AI"
    assert "HTTP-Referer" in request.headers


def test_keepalive_and_malformed_lines_are_tolerated() -> None:
    """OpenRouter emits ': comment' keep-alives; parsing must skip them."""
    body = (
        b": OPENROUTER PROCESSING\n"
        b'data: {"choices":[{"delta":{"content":"OK"}}]}\n'
        b"\n"
        b"data: not-json\n"
        b"\n"
        b"data: [DONE]\n"
        b"\n"
    )
    provider = ollama_raw(body)
    assert "".join(provider.stream_chat(CHAT)) == "OK"


def test_mid_stream_error_event_raises_provider_error() -> None:
    body = b'data: {"error": {"code": 429, "message": "rate limited"}}\n'
    provider = ollama_raw(body)
    with pytest.raises(ProviderError, match="rate limited"):
        list(provider.stream_chat(CHAT))


# --------------------------------------------------------------------- #
# error paths                                                            #
# --------------------------------------------------------------------- #


def test_401_becomes_provider_auth_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "invalid key"}})

    provider = OpenRouterProvider(
        base_url="https://test/api/v1",
        api_key="sk-bad",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(ProviderAuthError, match="invalid key"):
        list(provider.stream_chat(CHAT))


def test_500_becomes_provider_error_with_details() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"boom", headers={"content-type": "text/html"})

    provider = ollama_with(handler)
    with pytest.raises(ProviderError, match="500"):
        list(provider.stream_chat(CHAT))


def test_connection_refused_becomes_provider_unavailable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    provider = ollama_with(handler)
    with pytest.raises(ProviderUnavailableError, match="connection refused"):
        list(provider.stream_chat(CHAT))


# --------------------------------------------------------------------- #
# factory: provider switching + key requirements                          #
# --------------------------------------------------------------------- #

_ALL_FIELDS = {
    "ollama_base_url": "http://localhost:11434",
    "ollama_chat_model": "llama3.1:8b",
    "openrouter_base_url": "https://openrouter.ai/api/v1",
    "openrouter_api_key": "sk-test-offline",
    "openrouter_chat_model": "meta-llama/llama-3.3-70b-instruct:free",
}


def settings_for(provider: str, **overrides: object) -> SimpleNamespace:
    values = dict(_ALL_FIELDS)
    values.update(overrides)
    return SimpleNamespace(llm_provider=provider, **values)


def test_factory_builds_ollama_with_compatible_url() -> None:
    provider = build_provider(settings_for("ollama"))
    assert provider.provider_name == "ollama"
    assert provider.model == "llama3.1:8b"
    assert provider._client.base_url.path.rstrip("/") == "/v1"  # OpenAI-compat suffix


def test_factory_builds_openrouter_with_key() -> None:
    provider = build_provider(settings_for("openrouter"))
    assert provider.provider_name == "openrouter"
    assert provider.model.endswith(":free")


def test_factory_requires_openrouter_key() -> None:
    with pytest.raises(MissingAPIKeyError, match="OPENROUTER_API_KEY"):
        build_provider(settings_for("openrouter", openrouter_api_key=""))


def test_factory_serves_fake_provider() -> None:
    provider = build_provider(SimpleNamespace(llm_provider="fake"))
    assert provider.provider_name == "fake"
    assert list(provider.stream_chat(CHAT)) == ["The", "answer", "is", "42."]


def test_factory_rejects_unknown_provider() -> None:
    with pytest.raises(UnsupportedProviderError, match="skynet"):
        build_provider(SimpleNamespace(llm_provider="skynet"))


# --------------------------------------------------------------------- #
# FakeLLMProvider contract                                               #
# --------------------------------------------------------------------- #


def test_fake_provider_records_calls_and_streams_chunks() -> None:
    provider = FakeLLMProvider(chunks=["alpha", "beta"])
    assert list(provider.stream_chat(CHAT)) == ["alpha", "beta"]
    assert provider.calls == [list(CHAT)]


def test_fake_provider_can_simulate_failure() -> None:
    provider = FakeLLMProvider(error=FakeLLMProvider.unavailable())
    with pytest.raises(ProviderError, match="simulated backend crash"):
        list(provider.stream_chat(CHAT))
