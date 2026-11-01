"""`/api/chat` (SSE) and `/api/conversations` endpoints.

The POST body is validated *synchronously* (empty question → 400, unknown
conversation → 404) BEFORE the streaming response begins; everything that
happens after the stream opens is an in-stream ``error`` event, because the
status code is already committed.

SSE protocol (all payloads JSON):
    event: meta   {conversation_id, has_context, top_k, citations: [...]}
    event: delta  {text}
    event: error  {kind, message}
    event: done   {conversation_id}
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import TYPE_CHECKING

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.rag_pipeline import ChatError, ConversationNotFoundError, PipelineEvent

if TYPE_CHECKING:  # type hints only — avoids instantiation at import
    from app.core.rag_pipeline import RAGPipeline

router = APIRouter()


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    conversation_id: str | None = None
    top_k: int | None = Field(default=None, ge=1, le=20)


class MessageOut(BaseModel):
    role: str
    content: str
    citations: list[dict] | None
    created_at: str


class ConversationOut(BaseModel):
    id: str
    title: str
    created_at: str
    message_count: int


def _pipeline(request: Request) -> RAGPipeline:
    pipeline = getattr(request.app.state, "rag_pipeline", None)
    if pipeline is None:  # pragma: no cover — lifespan guarantees it
        raise HTTPException(status_code=503, detail="chat pipeline not initialized")
    return pipeline


def _format_sse(event: PipelineEvent) -> str:
    data = json.dumps(event.payload, ensure_ascii=False)
    return f"event: {event.name}\ndata: {data}\n\n"


def _sse_stream(events: Iterator[PipelineEvent]) -> Iterator[str]:
    return (_format_sse(event) for event in events)


@router.post("/chat", response_class=StreamingResponse)
def chat(request: Request, body: ChatRequest) -> StreamingResponse:
    pipeline = _pipeline(request)

    # Synchronous validation errors surface as proper HTTP failures;
    # in-stream failures surface as SSE `error` events.
    try:
        pipeline.validate_question(body.question)
        pipeline.require_conversation(body.conversation_id)
    except ChatError as exc:
        status = 404 if isinstance(exc, ConversationNotFoundError) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc

    return StreamingResponse(
        _sse_stream(
            pipeline.stream_events(
                question=body.question,
                conversation_id=body.conversation_id,
                top_k=body.top_k,
            )
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable proxy buffering (nginx et al.)
        },
    )


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(request: Request) -> list[ConversationOut]:
    return [
        ConversationOut(
            id=summary.id,
            title=summary.title,
            created_at=summary.created_at,
            message_count=summary.message_count,
        )
        for summary in _pipeline(request)._conversations.list()  # noqa: SLF001 — same app
    ]


@router.get("/conversations/{conversation_id}/messages", response_model=list[MessageOut])
def get_conversation_messages(request: Request, conversation_id: str) -> list[MessageOut]:
    repo = _pipeline(request)._conversations
    if not repo.exists(conversation_id):
        raise HTTPException(status_code=404, detail=f"conversation {conversation_id!r} not found")
    return [
        MessageOut(
            role=message.role,
            content=message.content,
            citations=message.citations,
            created_at=message.created_at,
        )
        for message in repo.messages(conversation_id)
    ]


class RenameConversationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)


@router.patch("/conversations/{conversation_id}", response_model=ConversationOut)
def rename_conversation(
    request: Request, conversation_id: str, body: RenameConversationRequest
) -> ConversationOut:
    """Rename a conversation (M6)."""
    repo = _pipeline(request)._conversations
    title = body.title.strip()
    if not title:
        raise HTTPException(status_code=400, detail="title must not be empty")
    try:
        repo.rename(conversation_id, title)
    except KeyError as exc:  # ConversationNotFoundError subclasses KeyError
        raise HTTPException(status_code=404, detail=f"conversation {conversation_id!r} not found") from exc
    summary = next(s for s in repo.list() if s.id == conversation_id)
    return ConversationOut(
        id=summary.id,
        title=summary.title,
        created_at=summary.created_at,
        message_count=summary.message_count,
    )


@router.delete("/conversations/{conversation_id}", status_code=204)
def delete_conversation(request: Request, conversation_id: str) -> None:
    """Delete a conversation and its messages (M6)."""
    repo = _pipeline(request)._conversations
    try:
        repo.delete(conversation_id)
    except KeyError as exc:  # ConversationNotFoundError subclasses KeyError
        raise HTTPException(status_code=404, detail=f"conversation {conversation_id!r} not found") from exc
