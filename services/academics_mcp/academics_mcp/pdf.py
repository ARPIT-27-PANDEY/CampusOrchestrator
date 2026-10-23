"""PDF text extraction that preserves 1-based page numbers."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pymupdf


class PdfExtractionError(RuntimeError):
    pass


@dataclass(frozen=True)
class PageText:
    page_number: int  # 1-based, matches what a reader sees in a PDF viewer
    text: str


@dataclass(frozen=True)
class ExtractedDocument:
    path: Path
    title: str
    content_hash: str  # sha256 of the file bytes; acts as the document version
    pages: list[PageText]


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 16), b""):
            h.update(block)
    return h.hexdigest()


def extract_pdf(path: Path) -> ExtractedDocument:
    if not path.exists():
        raise PdfExtractionError(f"File not found: {path.name}")
    try:
        with pymupdf.open(path) as doc:  # type: ignore[no-untyped-call]
            title = (doc.metadata or {}).get("title") or path.stem.replace("_", " ").title()
            pages = [PageText(page_number=i + 1, text=page.get_text("text")) for i, page in enumerate(doc)]
    except (pymupdf.FileDataError, RuntimeError, ValueError) as exc:
        raise PdfExtractionError(f"Could not read PDF {path.name}: {type(exc).__name__}") from exc
    return ExtractedDocument(path=path, title=title, content_hash=file_sha256(path), pages=pages)
