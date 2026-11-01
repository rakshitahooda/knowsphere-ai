"""M3 tests: document parsing (PDF page numbers, TXT/MD/DOCX, error cases).

PDF samples are GENERATED with PyMuPDF (needs requirements-ml.txt installed);
the suite stays offline.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.ingestion.parse import (
    DocumentParseError,
    EmptyDocumentError,
    TextSection,
    UnsupportedDocumentError,
    parse_document,
)

# --------------------------------------------------------------------- #
# helpers                                                                #
# --------------------------------------------------------------------- #


def make_pdf(path: Path, page_texts: list[str]) -> bytes:
    import pymupdf

    document = pymupdf.open()
    for text in page_texts:
        page = document.new_page()
        page.insert_text((72, 72), text)
    document.save(str(path))
    document.close()
    return path.read_bytes()


# --------------------------------------------------------------------- #
# happy paths                                                            #
# --------------------------------------------------------------------- #


def test_pdf_pages_are_extracted_with_numbers(tmp_path: Path) -> None:
    pdf_bytes = make_pdf(tmp_path / "sample.pdf", ["alpha content", "beta content"])
    sections = parse_document(pdf_bytes, "sample.pdf")

    assert [s.page for s in sections] == [1, 2]
    assert "alpha" in sections[0].text
    assert "beta" in sections[1].text
    assert [s.section for s in sections] == [1, 2]


def test_txt_is_one_section_without_page(tmp_path: Path) -> None:
    sections = parse_document("first paragraph\n\nsecond paragraph".encode(), "notes.txt")

    assert len(sections) == 1
    assert sections[0].page is None
    assert sections[0].section == 1
    assert "second paragraph" in sections[0].text


def test_md_uses_the_plaintext_path(tmp_path: Path) -> None:
    sections = parse_document("# Header\n\nSome markdown **text**".encode(), "readme.md")

    assert len(sections) == 1
    assert "# Header" in sections[0].text  # raw text, no markdown rendering


def test_docx_paragraphs_are_extracted(tmp_path: Path) -> None:
    from docx import Document as WordDocument

    docx_path = tmp_path / "memo.docx"
    document = WordDocument()
    document.add_paragraph("alpha bravo charlie")
    document.add_paragraph("delta echo foxtrot")
    document.save(str(docx_path))

    sections = parse_document(docx_path.read_bytes(), "memo.docx")

    assert len(sections) == 1
    assert "delta echo foxtrot" in sections[0].text


def test_non_utf8_txt_falls_back_to_cp1252(tmp_path: Path) -> None:
    sections = parse_document(b"caf\xe9 au lait", "legacy.txt")  # é in cp1252

    assert "café" in sections[0].text


# --------------------------------------------------------------------- #
# error taxonomy                                                         #
# --------------------------------------------------------------------- #


def test_corrupted_pdf_raises_parse_error(tmp_path: Path) -> None:
    with pytest.raises(DocumentParseError):
        parse_document(b"%PDF-1.4 this is not really a pdf", "broken.pdf")


def test_password_protected_pdf_message(tmp_path: Path) -> None:
    import pymupdf

    protected = tmp_path / "secret.pdf"
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "classified")
    document.save(
        str(protected), encryption=pymupdf.PDF_ENCRYPT_AES_256, owner_pw="pw", user_pw="pw"
    )
    document.close()

    with pytest.raises(DocumentParseError, match="password"):
        parse_document(protected.read_bytes(), "secret.pdf")


def test_corrupted_docx_raises_parse_error(tmp_path: Path) -> None:
    with pytest.raises(DocumentParseError):
        parse_document(b"PK this is not a zip archive really", "broken.docx")


def test_empty_txt_raises_empty_error(tmp_path: Path) -> None:
    with pytest.raises(EmptyDocumentError):
        parse_document(b"   \n\t ", "void.txt")


def test_unsupported_extension_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(UnsupportedDocumentError, match="\\.exe"):
        parse_document(b"MZ fake executable", "setup.exe")


def test_sections_carried_by_api_contract(tmp_path: Path) -> None:
    """TextSection stays frozen dataclass with stable field names."""
    section = TextSection(text="x", page=3, section=4)
    assert (section.text, section.page, section.section) == ("x", 3, 4)
