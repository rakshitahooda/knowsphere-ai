"""The RAG query pipeline — retrieval → prompt → provider streaming → SSE.

Everything crosses established boundaries only: retrieval via ``Retriever``
(Embedder + vector store), generation via the ``LLMProvider`` protocol,
history via ``ConversationRepository``. This module owns:

- the SSE event protocol (``PipelineEvent``: meta → delta* → done|error)
- prompt assembly with injection defense (context is untrusted data)
- the deterministic "no relevant context" path (no LLM call, zero citations)
- conversation persistence, including partial answers on interrupted streams
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.core.llm import ChatMessage, LLMProvider
from app.core.retrieval.retriever import Retriever
from app.core.retrieval.vector_store import RetrievedChunk
from app.db.conversations import ConversationRepository
from app.db.repository import DocumentNotFoundError, DocumentRepository

_MAX_QUESTION_LEN = 4000
_SNIPPET_LEN = 240
_TOP_K_MIN, _TOP_K_MAX = 1, 20


@dataclass(frozen=True, slots=True)
class PipelineEvent:
    """One SSE event; ``name`` ∈ {meta, delta, error, done}."""

    name: str
    payload: dict


class ChatError(Exception):
    """Malformed chat request (route maps to HTTP 400)."""


class ConversationNotFoundError(ChatError):
    """Referenced conversation does not exist (route maps to HTTP 404)."""


@lru_cache(maxsize=8)
def _load_prompt(name: str) -> str:
    return (Path(__file__).resolve().parents[1] / "prompts" / name).read_text(encoding="utf-8")


def _error_kind(exc: Exception) -> str:
    from app.core.llm.base import ProviderUnavailableError

    if isinstance(exc, ProviderUnavailableError):
        return "provider_unavailable"
    return type(exc).__name__


class RAGPipeline:
    def __init__(
        self,
        *,
        retriever: Retriever,
        provider: LLMProvider | None,
        conversations: ConversationRepository,
        documents: DocumentRepository,
        top_k: int = 5,
        history_limit: int = 8,
        provider_config_error: str | None = None,
    ) -> None:
        self._retriever = retriever
        self._provider = provider
        self._conversations = conversations
        self._documents = documents
        self._top_k = max(_TOP_K_MIN, min(_TOP_K_MAX, top_k))
        self._history_limit = max(0, history_limit)
        self._provider_config_error = provider_config_error

    # ------------------------------------------------------------------ #
    # synchronous pre-validation (route calls these BEFORE streaming)     #
    # ------------------------------------------------------------------ #

    def validate_question(self, question: str) -> None:
        if not question or not question.strip():
            raise ChatError("question must not be empty")
        if len(question) > _MAX_QUESTION_LEN:
            raise ChatError(f"question too long (max {_MAX_QUESTION_LEN} characters)")

    def require_conversation(self, conversation_id: str | None) -> None:
        if conversation_id and not self._conversations.exists(conversation_id):
            raise ConversationNotFoundError(f"conversation {conversation_id!r} not found")

    # ------------------------------------------------------------------ #
    # main streaming flow                                                 #
    # ------------------------------------------------------------------ #

    def stream_events(
        self,
        *,
        question: str,
        conversation_id: str | None = None,
        top_k: int | None = None,
    ) -> Iterator[PipelineEvent]:
        """Emit meta → delta* → done|error. Raises only ValueError-family
        validation *before* the first yield; everything after start is an
        in-stream ``error`` event (the response has already begun)."""
        self.validate_question(question)
        question = question.strip()
        effective_top_k = max(_TOP_K_MIN, min(_TOP_K_MAX, int(top_k or self._top_k)))

        if conversation_id is None:
            conversation_id = self._conversations.create(title=question[:120])
        elif not self._conversations.exists(conversation_id):
            raise ConversationNotFoundError(f"conversation {conversation_id!r} not found")

        history = self._conversations.messages(conversation_id, limit=self._history_limit)

        hits = self._retriever.retrieve(question, top_k=effective_top_k)
        pairs = self._match_citations(hits)  # [(chunk, citation), ...] ordered
        citations = [citation for _, citation in pairs]

        # Persist the user turn before generation: even an interrupted
        # stream leaves a consistent history.
        self._conversations.append(conversation_id, "user", question)

        buffer: list[str] = []
        assistant_saved = False
        try:
            yield PipelineEvent(
                "meta",
                {
                    "conversation_id": conversation_id,
                    "has_context": bool(pairs),
                    "top_k": effective_top_k,
                    "citations": citations,
                },
            )

            if not pairs:
                # Deterministic limitation answer — no LLM call, no citations.
                answer = _load_prompt("no_context.txt").strip()
                buffer.append(answer)
                yield PipelineEvent("delta", {"text": answer})
                self._conversations.append(
                    conversation_id, "assistant", answer, None
                )
                assistant_saved = True
                yield PipelineEvent("done", {"conversation_id": conversation_id})
                return

            if self._provider is None:
                yield self._error_event(
                    "provider_not_configured",
                    self._provider_config_error
                    or "LLM provider is not configured on the server",
                )
                return

            messages = self._build_messages(history, question, pairs)
            try:
                for chunk in self._provider.stream_chat(messages):
                    buffer.append(chunk)
                    yield PipelineEvent("delta", {"text": chunk})
            except Exception as exc:  # provider died mid — or at — stream start
                if buffer:
                    self._conversations.append(
                        conversation_id,
                        "assistant",
                        "".join(buffer),
                        citations or None,
                    )
                    assistant_saved = True
                yield self._error_event(_error_kind(exc), str(exc))
                return
            self._conversations.append(
                conversation_id, "assistant", "".join(buffer), citations or None
            )
            assistant_saved = True
            yield PipelineEvent("done", {"conversation_id": conversation_id})
        finally:
            # Abrupt client disconnect (GeneratorExit) or early close: save
            # whatever partial answer exists so history stays consistent.
            if buffer and not assistant_saved:
                try:
                    self._conversations.append(
                        conversation_id,
                        "assistant",
                        "".join(buffer),
                        citations or None,
                    )
                except Exception:  # noqa: BLE001 — persistence must not crash close
                    pass

    # ------------------------------------------------------------------ #
    # prompt assembly                                                     #
    # ------------------------------------------------------------------ #

    def _build_messages(
        self,
        history: Sequence[object],  # ConversationRepository.Message rows
        question: str,
        pairs: Sequence[tuple[RetrievedChunk, dict]],
    ) -> list[ChatMessage]:
        messages: list[ChatMessage] = [
            ChatMessage(role="system", content=_load_prompt("rag_system.txt"))
        ]
        for message in history:
            if getattr(message, "role", None) in ("user", "assistant"):
                content = getattr(message, "content", "")
                if content.strip():
                    messages.append(
                        ChatMessage(role=message.role, content=message.content)
                    )
        if pairs:
            context = self._render_context(pairs)
            user_text = f"<context>\n{context}\n</context>\n\nQUESTION:\n{question}"
        else:
            user_text = f"QUESTION:\n{question}"
        messages.append(ChatMessage(role="user", content=user_text))
        return messages

    @staticmethod
    def _render_context(pairs: Sequence[tuple[RetrievedChunk, dict]]) -> str:
        blocks: list[str] = []
        for position, (chunk, citation) in enumerate(pairs, start=1):
            page = citation["page"]
            page_text = f"page {page}" if page is not None else "no page number"
            label = (
                f'[doc "{citation["document_name"]}" | {page_text} '
                f"| chunk {citation['chunk_index']} | ref #{position}]"
            )
            blocks.append(f"{label}\n{chunk.text}")
        return "\n\n".join(blocks)

    def _match_citations(self, hits: Sequence[RetrievedChunk]) -> list[tuple[RetrievedChunk, dict]]:
        """Attach document metadata to hits; drops hits whose document no
        longer exists (defensive — deletion removes vectors first)."""
        pairs: list[tuple[RetrievedChunk, dict]] = []
        for position, hit in enumerate(hits, start=1):
            try:
                document = self._documents.get(hit.document_id)
            except DocumentNotFoundError:
                continue  # never fabricate a citation for a missing doc
            citation = {
                "position": position,
                "document_id": hit.document_id,
                "document_name": document.original_name,
                "page": hit.page,
                "section": hit.section,
                "chunk_index": hit.chunk_index,
                "reference": self._reference(hit),
                "snippet": hit.text[:_SNIPPET_LEN],
            }
            pairs.append((hit, citation))
        return pairs

    @staticmethod
    def _reference(hit: RetrievedChunk) -> str:
        page = f"p{hit.page}" if hit.page is not None else "np"
        return f"{page}·s{hit.section}"

    @staticmethod
    def _error_event(kind: str, message: str) -> PipelineEvent:
        return PipelineEvent("error", {"kind": kind, "message": message})
