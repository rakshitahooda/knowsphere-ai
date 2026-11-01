"""Factory: Settings-like object → concrete provider instance.

The adapters stay pure (HTTP, no config knowledge); *this* module knows
settings and wires them up. OpenRouter's key requirement is validated here —
at construction time, before any network call — so a misconfiguration fails
fast with an actionable message instead of a 401 deep inside a stream.

``settings`` is duck-typed on purpose: tests exercise invalid combinations
via SimpleNamespace without breaking Settings' Literal validation.
"""

from __future__ import annotations

from typing import Any

from app.core.llm.base import MissingAPIKeyError, UnsupportedProviderError
from app.core.llm.fake import FakeLLMProvider
from app.core.llm.ollama import OllamaProvider
from app.core.llm.openrouter import OpenRouterProvider


def build_provider(settings: Any) -> Any:
    """Instantiate the provider named by ``settings.llm_provider``."""
    name = getattr(settings, "llm_provider", None)

    if name == "ollama":
        return OllamaProvider(
            base_url=str(getattr(settings, "ollama_base_url")).rstrip("/") + "/v1",
            model=getattr(settings, "ollama_chat_model"),
        )

    if name == "openrouter":
        api_key = getattr(settings, "openrouter_api_key", "")
        if not api_key.strip():
            raise MissingAPIKeyError(
                "LLM_PROVIDER is 'openrouter' but OPENROUTER_API_KEY is empty — "
                "set it in .env or switch LLM_PROVIDER=ollama (key-free default)",
                provider="openrouter",
            )
        return OpenRouterProvider(
            base_url=str(getattr(settings, "openrouter_base_url")).rstrip("/"),
            api_key=api_key,
            model=getattr(settings, "openrouter_chat_model"),
        )

    if name == "fake":
        return FakeLLMProvider()

    raise UnsupportedProviderError(
        f"no adapter registered for llm_provider={name!r}", provider=str(name)
    )
