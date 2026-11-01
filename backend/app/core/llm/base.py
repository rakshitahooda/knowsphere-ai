"""LLM provider boundary.

This module defines the *contract* every chat backend must honor:

- ``ChatMessage``: provider-neutral message type (no SDK types cross it).
- ``LLMProvider``: a structural protocol with a single streaming method. The
  RAG pipeline (M4) consumes tokens as an iterator so responses stream
  end-to-end regardless of backend.
- errors: a small hierarchy so callers can react to *kinds* of failures
  (not connected / bad credentials / other) without knowing backends.

Design rule: no logic that knows about a particular vendor belongs here.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True, slots=True)
class ChatMessage:
    """A single message in a conversation, provider-neutral."""

    role: Role
    content: str


@runtime_checkable
class LLMProvider(Protocol):
    """Contract for chat completion backends (local or cloud)."""

    #: Short identifier, e.g. "ollama", "openrouter", "fake".
    provider_name: str

    def stream_chat(self, messages: Sequence[ChatMessage]) -> Iterator[str]:
        """Yield the assistant reply as incremental text chunks."""
        ...


# --------------------------------------------------------------------- #
# Error hierarchy — kind-based, never vendor-specific                    #
# --------------------------------------------------------------------- #


class ProviderError(Exception):
    """Base class: one of two fields — which backend, human-readable why."""

    def __init__(self, message: str, *, provider: str) -> None:
        super().__init__(f"[{provider}] {message}")
        self.provider = provider


class ProviderUnavailableError(ProviderError):
    """The backend cannot be reached at all (connection refused, DNS...)."""

    def __init__(self, message: str, *, provider: str, hint: str | None = None) -> None:
        full = message if hint is None else f"{message} ({hint})"
        super().__init__(full, provider=provider)


class ProviderAuthError(ProviderError):
    """The backend rejected credentials (401/403)."""


class MissingAPIKeyError(ProviderError):
    """A required key is not configured (factory-level, checked early)."""


class UnsupportedProviderError(ProviderError):
    """The configured provider name has no registered adapter."""
