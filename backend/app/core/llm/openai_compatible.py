"""Shared HTTP client for OpenAI-compatible chat endpoints.

Ollama (``/v1/chat/completions``) and OpenRouter (``/api/v1/chat/completions``)
both implement the same OpenAI-style SSE protocol, so one implementation
serves both adapters. Using plain ``httpx`` (already a runtime dependency)
instead of an SDK keeps the dependency tree small and the behavior explicit.

Transport note: the constructor optionally accepts an ``httpx.BaseTransport``
so tests can inject ``httpx.MockTransport`` — no real network in unit tests.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from collections.abc import Sequence
from typing import Any

import httpx

from app.core.llm.base import (
    ChatMessage,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
)


class OpenAICompatibleProvider:
    """Streaming SSE client for an OpenAI-compatible backend."""

    def __init__(
        self,
        *,
        provider_name: str,
        base_url: str,
        model: str,
        api_key: str | None = None,
        extra_headers: Mapping[str, str] | None = None,
        timeout: float = 120.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        headers: dict[str, str] = {"Accept": "text/event-stream"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        if extra_headers:
            headers.update(extra_headers)
        self.provider_name = provider_name
        self.model = model
        self._client = httpx.Client(
            base_url=base_url,
            headers=headers,
            timeout=timeout,
            transport=transport,
        )

    def stream_chat(self, messages: Sequence[ChatMessage]) -> Iterator[str]:
        """Yield reply chunks from an SSE ``/chat/completions`` stream."""
        payload = {
            "model": self.model,
            "stream": True,
            "messages": [
                {"role": message.role, "content": message.content}
                for message in messages
            ],
        }
        try:
            with self._client.stream("POST", "/chat/completions", json=payload) as resp:
                self._raise_for_status(resp)
                for line in resp.iter_lines():
                    chunk = self._parse_sse_line(line)
                    if chunk is not None:
                        yield chunk
        except httpx.HTTPError as error:
            # ProviderError raised inside the `with` block is NOT an
            # httpx.HTTPError, so it lands here untouched and propagates.
            raise self._translate_http_error(error) from error

    # ------------------------------------------------------------------ #
    # internals                                                           #
    # ------------------------------------------------------------------ #

    def _raise_for_status(self, resp: httpx.Response) -> None:
        """Turn non-2xx HTTP statuses into typed provider errors."""

        def body_snippet() -> str:
            try:
                return resp.read().decode("utf-8", "replace")[:200]
            except Exception:  # noqa: BLE001 — stream may already be consumed
                return ""

        if resp.status_code in (401, 403):
            raise ProviderAuthError(
                f"HTTP {resp.status_code}: credentials rejected — {body_snippet()}",
                provider=self.provider_name,
            )
        if resp.status_code >= 400:
            detail = body_snippet()
            raise ProviderError(
                f"HTTP {resp.status_code}: {detail or 'unspecified error'}",
                provider=self.provider_name,
            )

    def _parse_sse_line(self, line: str) -> str | None:
        """Extract the delta text from one SSE line; ``None`` = no content."""
        if not line.startswith("data:"):
            return None  # empty separators and ": comment" keep-alive lines
        payload = line[len("data:") :].strip()
        if not payload or payload == "[DONE]":
            return None
        try:
            event: dict[str, Any] = json.loads(payload)
        except json.JSONDecodeError:
            return None  # tolerate non-JSON noise instead of killing the stream
        if error_msg := event.get("error"):  # mid-stream error events
            raise ProviderError(str(error_msg), provider=self.provider_name)
        choices = event.get("choices") or []
        delta = (choices[0].get("delta") or {}).get("content") if choices else None
        return delta if delta else None

    def _translate_http_error(self, error: httpx.HTTPError) -> ProviderError:
        provider = self.provider_name
        if isinstance(error, (httpx.ConnectError, httpx.ConnectTimeout)):
            hint = "is the backend running and reachable at the configured URL?"
            return ProviderUnavailableError(str(error), provider=provider, hint=hint)
        if isinstance(error, httpx.TimeoutException):
            return ProviderError(f"request timed out: {error}", provider=provider)
        return ProviderError(f"HTTP error: {error}", provider=provider)
