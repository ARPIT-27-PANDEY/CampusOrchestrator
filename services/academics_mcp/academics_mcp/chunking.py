"""Clause-aware chunking that never crosses a page boundary.

Keeping every chunk inside one page means each citation points to exactly one
page. Paragraphs are rebuilt from wrapped PDF lines, then packed into chunks of
at most ``max_chars``; oversized paragraphs are split on sentence boundaries.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .pdf import ExtractedDocument

_CLAUSE_START = re.compile(r"^(\d+\.\d+\s|Q:|Campus notice)")
_PARA_START = re.compile(r"^(Section\s+\d+\b|\d+\.\d+\s|Q:|A:|[A-Z]{2,5}\s\d{3}\s|Contents\b|Campus notice)")
_SECTION = re.compile(r"^Section\s+(\d+)\s*[-–:]\s*(.+?)$(?<!\))")
_FOOTER = re.compile(r"^DEMO DATA - .*Page \d+$")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    source_filename: str
    document_title: str
    document_version: str
    page_number: int
    chunk_index: int  # position within the page
    section: str
    text: str


def _paragraphs(page_text: str) -> list[str]:
    paras: list[str] = []
    for raw in page_text.splitlines():
        line = raw.strip()
        if not line or _FOOTER.match(line):
            continue
        # An answer belongs with its question: "A:" continues the preceding "Q:" paragraph.
        if paras and line.startswith("A:") and paras[-1].startswith("Q:"):
            paras[-1] = f"{paras[-1]} {line}"
        elif not paras or _PARA_START.match(line) or _SECTION.match(line):
            paras.append(line)
        else:
            paras[-1] = f"{paras[-1]} {line}"
    return paras


def _split_long(paragraph: str, max_chars: int) -> list[str]:
    if len(paragraph) <= max_chars:
        return [paragraph]
    parts: list[str] = []
    current = ""
    for sentence in _SENTENCE.split(paragraph):
        if current and len(current) + len(sentence) + 1 > max_chars:
            parts.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}".strip()
    if current:
        parts.append(current)
    return parts


def _make_chunk(
    doc: ExtractedDocument, doc_id: str, page_number: int, index: int, section: str, parts: list[str]
) -> Chunk:
    return Chunk(
        chunk_id=f"{doc_id}-p{page_number}-c{index}",
        doc_id=doc_id,
        source_filename=doc.path.name,
        document_title=doc.title,
        document_version=doc.content_hash[:12],
        page_number=page_number,
        chunk_index=index,
        section=section,
        text=" ".join(parts),
    )


def chunk_document(doc: ExtractedDocument, max_chars: int = 700, min_chars: int = 80) -> list[Chunk]:
    """Chunk per clause: each numbered clause or Q&A pair starts a new chunk once the buffer holds
    at least ``min_chars`` (so short headings travel with the first clause). Chunks stay within one page."""
    # doc_id identifies the *file* (stable across versions); document_version identifies its content.
    doc_id = hashlib.sha256(doc.path.name.encode()).hexdigest()[:12]
    section = doc.title
    chunks: list[Chunk] = []
    for page in doc.pages:
        buffer: list[str] = []
        buffer_section = section
        index = 0
        for para in _paragraphs(page.text):
            heading = _SECTION.match(para)
            if heading:
                section = f"Section {heading.group(1)} - {heading.group(2).strip()}"
            for k, piece in enumerate(_split_long(para, max_chars)):
                starts_section = heading is not None and k == 0
                buffered = len(" ".join(buffer))
                too_long = bool(buffer) and buffered + len(piece) + 1 > max_chars
                new_clause = k == 0 and bool(_CLAUSE_START.match(piece)) and buffered >= min_chars
                if buffer and (starts_section or too_long or new_clause):
                    chunks.append(_make_chunk(doc, doc_id, page.page_number, index, buffer_section, buffer))
                    index += 1
                    buffer = []
                if not buffer:
                    buffer_section = section
                buffer.append(piece)
        if buffer:
            chunks.append(_make_chunk(doc, doc_id, page.page_number, index, buffer_section, buffer))
    return chunks
