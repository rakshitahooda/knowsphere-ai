"""Deterministic offline LLM provider for unit tests and pipelines.

``FakeLLMProvider`` is registered in the factory (provider name ``"fake"``)
so the RAG pipeline (M4) can run end-to-end with zero network and zero model
downloads — retrieval, prompt assembly and streaming logic all get exercised
against it. It records every call for assertions.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence

from app.core.llm.base import ChatMessage, ProviderError


class FakeLLMProvider:
    """Configurable canned-reply provider; never touches the network."""

    provider_name = "fake"

    def __init__(
        self,
        *,
        reply: str = "The answer is 42.",
        chunks: list[str] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.reply = reply
        self.chunks = chunks  # if set, stream these verbatim instead of reply split
        self.error = error  # if set, raise this while streaming
        self.calls: list[list[ChatMessage]] = []

    def stream_chat(self, messages: Sequence[ChatMessage]) -> Iterator[str]:
        self.calls.append(list(messages))
        if self.error is not None:
            raise self.error
        if self.chunks is not None:
            yield from self.chunks
            return
        yield from self.reply.split(" ")

    @staticmethod
    def unavailable() -> ProviderError:
        """Prebuilt ready-to-raise error for 'provider offline' tests."""
        return ProviderError("simulated backend crash", provider="fake")
