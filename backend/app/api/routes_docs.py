"""`/api/documents` — upload, list, inspect, delete.

The routes are intentionally thin: validation/ingestion logic (and the
capability to run it with fake embedders in tests) lives in the pipeline;
the only job here is HTTP translation of the IngestionError taxonomy:

- FileTooLargeError       → 413
- UnsupportedDocument     → 415
- DuplicateDocument       → 409
- EmptyDocument           → 400
- DocumentParseError      → 400 (corrupted / unreadable)
- DocumentNotFoundError   → 404
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from pydantic import BaseModel

from app.ingestion.parse import (
    DocumentParseError,
    EmptyDocumentError,
    IngestionError,
    UnsupportedDocumentError,
)

from app.db.repository import DocumentNotFoundError, DocumentMeta
from app.ingestion.pipeline import (
    DocumentIngestor,
    DocumentNotFoundError as PipelineDocumentNotFound,
    DuplicateDocumentError,
    FileTooLargeError,
)

router = APIRouter()


class DocumentOut(BaseModel):
    id: str
    original_name: str
    stored_name: str
    content_type: str
    size_bytes: int
    num_chunks: int
    status: str
    created_at: str


def _ingestor(request: Request) -> DocumentIngestor:
    """Built once in the lifespan; tests inject fakes via Settings."""
    ingestor = getattr(request.app.state, "ingestor", None)
    if ingestor is None:  # pragma: no cover — lifespan guarantees it
        raise HTTPException(status_code=503, detail="ingestor not initialized")
    return ingestor


def _to_out(meta: DocumentMeta) -> DocumentOut:
    return DocumentOut(
        id=meta.id,
        original_name=meta.original_name,
        stored_name=meta.stored_name,
        content_type=meta.content_type,
        size_bytes=meta.size_bytes,
        num_chunks=meta.num_chunks,
        status=meta.status,
        created_at=meta.created_at,
    )


@router.post("/documents", response_model=DocumentOut, status_code=201)
async def upload_document(
    request: Request,
    file: Annotated[UploadFile, File(description="PDF, TXT, MD or DOCX (≤ 20 MB)")],
) -> DocumentOut:
    data = await file.read()
    try:
        meta = _ingestor(request).ingest(
            original_name=file.filename or "",
            data=data,
            content_type=file.content_type,
        )
    except IngestionError as exc:
        raise _map_ingestion_error(exc) from exc
    return _to_out(meta)


@router.get("/documents", response_model=list[DocumentOut])
async def list_documents(request: Request) -> list[DocumentOut]:
    return [_to_out(meta) for meta in _ingestor(request).list_documents()]


@router.get("/documents/{document_id}", response_model=DocumentOut)
async def get_document(request: Request, document_id: str) -> DocumentOut:
    try:
        meta = _ingestor(request).get_document(document_id)
    except (DocumentNotFoundError, PipelineDocumentNotFound):
        raise HTTPException(
            status_code=404, detail=f"document {document_id!r} not found"
        ) from None
    return _to_out(meta)


@router.delete("/documents/{document_id}", status_code=204)
async def delete_document(request: Request, document_id: str) -> None:
    try:
        _ingestor(request).delete_document(document_id)
    except (DocumentNotFoundError, PipelineDocumentNotFound):
        raise HTTPException(
            status_code=404, detail=f"document {document_id!r} not found"
        ) from None


_ERROR_STATUS: dict[type[IngestionError], int] = {
    FileTooLargeError: 413,
    UnsupportedDocumentError: 415,
    DuplicateDocumentError: 409,
    EmptyDocumentError: 400,
    DocumentParseError: 400,
}
_FALLBACK_STATUS = 400


def _map_ingestion_error(exc: IngestionError) -> HTTPException:
    status = _ERROR_STATUS.get(type(exc), _FALLBACK_STATUS)
    return HTTPException(status_code=status, detail=str(exc))
