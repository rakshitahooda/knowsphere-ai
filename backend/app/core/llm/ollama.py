"""Ollama adapter — the DEFAULT provider: local, free, no API key."""

from __future__ import annotations

import httpx

from app.core.llm.openai_compatible import OpenAICompatibleProvider


class OllamaProvider(OpenAICompatibleProvider):
    """Chat completions against a local Ollama server.

    Uses Ollama's OpenAI-compatible endpoint (``<base_url>/v1/chat/completions``),
    available on every modern Ollama release on Windows.
    """

    provider_name = "ollama"

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:11434/v1",
        model: str = "llama3.1:8b",
        timeout: float = 300.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        super().__init__(
            provider_name=self.provider_name,
            base_url=base_url,
            model=model,
            timeout=timeout,
            transport=transport,  # test seam only
        )
