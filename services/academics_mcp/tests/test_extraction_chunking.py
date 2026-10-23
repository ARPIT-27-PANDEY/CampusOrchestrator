"""PDF extraction, page boundaries and chunk metadata."""

from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest

from academics_mcp.chunking import chunk_document
from academics_mcp.pdf import PdfExtractionError, extract_pdf


def _make_pdf(path: Path, pages: list[str], title: str = "Test Doc") -> Path:
    doc = pymupdf.open()
    doc.set_metadata({"title": title})
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 550, 800), text, fontsize=10)
    doc.save(path)
    return path


def test_extraction_preserves_one_based_page_numbers(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "a.pdf", ["Alpha page text.", "Beta page text.", "Gamma page text."])
    doc = extract_pdf(pdf)
    assert [p.page_number for p in doc.pages] == [1, 2, 3]
    assert "Beta" in doc.pages[1].text and "Beta" not in doc.pages[0].text
    assert doc.title == "Test Doc"
    assert len(doc.content_hash) == 64


def test_chunks_never_cross_page_boundaries(tmp_path: Path) -> None:
    long_para = " ".join(f"Sentence {i} about attendance rules." for i in range(60))
    pdf = _make_pdf(tmp_path / "b.pdf", [f"Section 1 - Rules\n1.1 {long_para}", "Section 2 - Other\n2.1 Final clause."])
    chunks = chunk_document(extract_pdf(pdf), max_chars=400)
    assert all(len(c.text) <= 400 + 60 for c in chunks)  # sentence-granular split
    page1 = [c for c in chunks if c.page_number == 1]
    page2 = [c for c in chunks if c.page_number == 2]
    assert page1 and page2
    assert all("Final clause" not in c.text for c in page1)
    assert all(c.section == "Section 1 - Rules" for c in page1)
    assert page2[0].section == "Section 2 - Other"


def test_chunk_metadata_complete_and_ids_unique(tmp_path: Path) -> None:
    pdf = _make_pdf(tmp_path / "c.pdf", ["Section 1 - A\n1.1 One.\n1.2 Two.", "Section 2 - B\n2.1 Three."])
    doc = extract_pdf(pdf)
    chunks = chunk_document(doc)
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))
    for c in chunks:
        assert c.source_filename == "c.pdf"
        assert c.document_version == doc.content_hash[:12]
        assert c.chunk_id.startswith(f"{c.doc_id}-p{c.page_number}-c")


def test_table_of_contents_lines_are_not_sections(tmp_path: Path) -> None:
    pdf = _make_pdf(
        tmp_path / "toc.pdf", ["Handbook\nContents\nSection 1 - Attendance (page 2)", "Section 1 - Attendance\n1.1 Go."]
    )
    chunks = chunk_document(extract_pdf(pdf))
    assert chunks[0].section == "Test Doc"
    assert chunks[-1].section == "Section 1 - Attendance"


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(PdfExtractionError):
        extract_pdf(tmp_path / "missing.pdf")


def test_corrupt_file_raises(tmp_path: Path) -> None:
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"not a pdf at all")
    with pytest.raises(PdfExtractionError):
        extract_pdf(bad)


def test_blank_pdf_produces_no_chunks(tmp_path: Path) -> None:
    doc = pymupdf.open()
    doc.new_page()
    path = tmp_path / "blank.pdf"
    doc.save(path)
    assert chunk_document(extract_pdf(path)) == []
