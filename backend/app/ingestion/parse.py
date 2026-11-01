"""Document parsing: raw bytes → structured text sections.

Every parser returns ``list[TextSection]`` — the atomic *source metadata*
unit the rest of the pipeline carries through chunking and indexing. For
PDFs a section is a page (satisfying "extract PDF page numbers"); for plain
text/MD/DOCX the whole document is one section with ``page=None`` since
those formats have no page concept.

Parsers consume the IN-MEMORY bytes, never the stored file: on Windows an
open path-backed handle trapped in a raised traceback keeps the file locked
until the exception is garbage-collected. Parsing from memory eliminates
that class of bug entirely.

Failure taxonomy used by routes/pipeline (each maps to a distinct HTTP status):
- UnsupportedDocumentError → unknown extension (415)
- EmptyDocumentError      → parsed to nothing useful (400)
- DocumentParseError      → unreadable/corrupted/password-protected (400)
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Callable  # noqa: F401 — kept: parser dispatch table type

SUPPORTED_SUFFIXES: frozenset[str] = frozenset({".pdf", ".txt", ".md", ".markdown", ".docx"})


class IngestionError(Exception):
    """Base for the ingestion domain (pipeline + parser + chunker)."""


class UnsupportedDocumentError(IngestionError):
    pass


class EmptyDocumentError(IngestionError):
    pass


class DocumentParseError(IngestionError):
    pass


@dataclass(frozen=True, slots=True)
class TextSection:
    """One logical block of source text with provenance metadata."""

    text: str
    page: int | None  # 1-based page number (PDF only; None = not applicable)
    section: int  # 1-based ordinal of the block within the document


def parse_document(data: bytes, original_name: str) -> list[TextSection]:
    """Parse *any* supported document from its raw bytes into sections.

    Format is decided by ``original_name``'s suffix.
    """
    suffix = Path(original_name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
        raise UnsupportedDocumentError(
            f"unsupported document type {suffix!r} (supported: {supported})"
        )

    parser: Callable[[bytes], list[TextSection]] = _PARSERS[suffix]
    try:
        sections = [s for s in parser(data) if s.text.strip()]
    except IngestionError:
        raise  # deliberately raise our own taxonomy untouched
    except Exception as exc:  # noqa: BLE001 — parser libs raise many types
        raise DocumentParseError(f"failed to parse {suffix!r} document: {exc}") from exc

    if not sections:
        raise EmptyDocumentError(f"{Path(original_name).name!r} contains no extractable text")
    return sections


# --------------------------------------------------------------------- #
# format-specific parsers                                                 #
# --------------------------------------------------------------------- #


def _parse_pdf(data: bytes) -> list[TextSection]:
    try:
        import pymupdf  # deferred: pulls heavy bindings at import
    except ImportError as exc:  # clear message instead of raw traceback
        raise DocumentParseError(
            "pymupdf is not installed — run: pip install -r requirements-ml.txt"
        ) from exc

    # stream= keeps the file handle count at zero; the stored copy on disk
    # is purely the archive.
    with pymupdf.open(stream=data, filetype="pdf") as doc:
        if doc.needs_pass:
            raise DocumentParseError("PDF is password-protected")
        sections: list[TextSection] = []
        for page_number, page in enumerate(doc, start=1):
            text = page.get_text("text")
            if text and text.strip():
                sections.append(TextSection(text=text, page=page_number, section=page_number))
    return sections


def _parse_plaintext(data: bytes) -> list[TextSection]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        # Windows-friendly fallback for legacy 8-bit encodings (cp1252 etc.)
        text = data.decode("cp1252", errors="replace")
    if not text.strip():
        return []
    return [TextSection(text=text, page=None, section=1)]


def _parse_docx(data: bytes) -> list[TextSection]:
    try:
        from docx import Document as WordDocument  # deferred, lightweight
    except ImportError as exc:
        raise DocumentParseError(
            "python-docx is not installed — run: pip install -r requirements-ml.txt"
        ) from exc

    document = WordDocument(io.BytesIO(data))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    if not text.strip():
        return []
    return [TextSection(text=text, page=None, section=1)]


_PARSERS: dict[str, Callable[[bytes], list[TextSection]]] = {
    ".pdf": _parse_pdf,
    ".txt": _parse_plaintext,
    ".md": _parse_plaintext,
    ".markdown": _parse_plaintext,
    ".docx": _parse_docx,
}
