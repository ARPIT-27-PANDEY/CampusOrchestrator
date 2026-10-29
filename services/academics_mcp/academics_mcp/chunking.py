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


_PAGE_NUMBER = re.compile(r"^\d{1,3}$")
_NOISE = re.compile(r"^(\*{3,}|[~|_.\-\s]{1,6})$")
_CLAUSE = re.compile(r"^(\(\d{1,2}\)|\([a-z]\)|\([ivx]{1,4}\)|\d{1,2}\.(?!\d)|[a-z]\.\s|[ivx]{1,4}\.\s)")
_SUBJECT = re.compile(r"^(Sub(?:ject)?|S~bject)\s*:\s*(?P<s>.+)", re.I)
_ORD_NUMBER = re.compile(r"^\d{1,2}[a-z]?$")


_SMALL_WORDS = {"and", "or", "of", "the", "for", "in", "on", "to", "a", "an", "with", "by", "at", "from", "under"}


def _title_like(line: str) -> bool:
    """Short line without sentence punctuation or commas, mostly letters, mostly Capitalised words."""
    words = line.split()
    if not (3 <= len(line) <= 60 and 1 <= len(words) <= 8) or not line[0].isupper():
        return False
    if line.endswith((".", ",", ";", ":")) or "," in line or _CLAUSE.match(line):
        return False
    if sum(c.isalpha() for c in line) < 0.7 * len(line.replace(" ", "")):
        return False
    content = [w for w in words if w.lower() not in _SMALL_WORDS]
    return bool(content) and sum(w[0].isupper() for w in content) / len(content) >= 0.6


def _is_heading(lines: list[str], i: int) -> bool:
    """A heading needs a strong signal: an ordinance number or a clause marker right after it."""
    if not _title_like(lines[i]):
        return False
    nxt = lines[i + 1] if i + 1 < len(lines) else ""
    return bool(_ORD_NUMBER.match(nxt) or _CLAUSE.match(nxt))


def chunk_official(
    doc: ExtractedDocument, max_chars: int = 900, min_chars: int = 120, *, headings: bool = True
) -> list[Chunk]:
    """General chunker for official PDFs (ordinances, notifications, calendars).

    Sections come from margin headings (plus a following ordinance number such as "26") or a
    notification's "Subject:" line. A new chunk starts at a new heading, or at a numbered clause
    once the buffer is reasonably full. Chunks never cross a page, so every citation is one page.
    """
    doc_id = hashlib.sha256(doc.path.name.encode()).hexdigest()[:12]
    section = doc.title
    chunks: list[Chunk] = []
    for page in doc.pages:
        lines = [ln.strip() for ln in page.text.splitlines()]
        lines = [ln for ln in lines if ln and not _NOISE.match(ln)]
        if lines and _PAGE_NUMBER.match(lines[0]):
            lines = lines[1:]  # running page number
        buffer: list[str] = []
        buffer_section = section
        index = 0

        def flush(page_number: int, label: str) -> None:
            nonlocal buffer, index
            text = re.sub(r"\s+", " ", " ".join(buffer)).strip()
            if len(text) >= 20:
                chunks.append(_make_chunk(doc, doc_id, page_number, index, label, [text]))
                index += 1
            buffer = []

        i = 0
        while i < len(lines):
            line = lines[i]
            subject = _SUBJECT.match(line)
            heading = subject is not None or (headings and _is_heading(lines, i))
            if heading:
                title = subject.group("s").strip() if subject else line
                nxt = lines[i + 1] if i + 1 < len(lines) else ""
                if not subject and _ORD_NUMBER.match(nxt):
                    title = f"{nxt}. {title}"
                    i += 1
                if buffer and len(" ".join(buffer)) >= min_chars:
                    flush(page.page_number, buffer_section)
                section = title[:120]
                if not buffer:
                    buffer_section = section
                buffer.append(line if subject else "")
                i += 1
                continue
            buffered = len(" ".join(buffer))
            if buffer and (buffered + len(line) > max_chars or (_CLAUSE.match(line) and buffered >= max_chars // 2)):
                flush(page.page_number, buffer_section)
            if not buffer:
                buffer_section = section
            buffer.append(line)
            i += 1
        if buffer:
            flush(page.page_number, buffer_section)
    return chunks


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
