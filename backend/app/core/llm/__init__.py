"""Provider-agnostic LLM layer.

Public surface (what the rest of the app may import):
    ChatMessage, LLMProvider, build_provider, FakeLLMProvider,
    ProviderError (+ subclasses)

Everything else stays internal — app code never imports an SDK or an HTTP
client directly; that knowledge lives in the adapters.
"""

from app.core.llm.base import (
    ChatMessage,
    LLMProvider,
    MissingAPIKeyError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
    UnsupportedProviderError,
)
from app.core.llm.factory import build_provider
from app.core.llm.fake import FakeLLMProvider

__all__ = [
    "ChatMessage",
    "LLMProvider",
    "MissingAPIKeyError",
    "ProviderAuthError",
    "ProviderError",
    "ProviderUnavailableError",
    "UnsupportedProviderError",
    "build_provider",
    "FakeLLMProvider",
]
