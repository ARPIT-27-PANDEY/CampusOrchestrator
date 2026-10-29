"""Collect citations and source metadata from tool results, and verify answer citations.

Citations shown to the user are built from what the retrieval tool actually
returned, not from model text, so the UI can never display a fabricated reference.
``verify_citations`` additionally flags page references in the answer that no
retrieved passage supports.
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from ..mcp.models import ToolExecution, ToolStatus
from .models import Citation, CitationCheck, SourceRef

_REF = re.compile(r"\[([^\[\]]{2,120}?),\s*p(?:age|\.)?\s*(\d{1,4})\]", re.I)
_BARE_PAGE = re.compile(r"\bp(?:age|\.)\s*(\d{1,4})\b", re.I)


def collect_citations(executions: list[ToolExecution]) -> list[Citation]:
    seen: dict[str, Citation] = {}
    for ex in executions:
        if ex.status is not ToolStatus.SUCCESS or not ex.data:
            continue
        for p in ex.data.get("passages") or []:
            cid = str(p.get("citation_id"))
            if cid in seen or "page" not in p:
                continue
            seen[cid] = Citation(
                number=len(seen) + 1,
                citation_id=cid,
                document_title=str(p.get("document_title")),
                source_filename=str(p.get("source_filename")),
                document_version=str(p.get("document_version")),
                page=int(p["page"]),
                section=p.get("section"),
                excerpt=str(p.get("excerpt", ""))[:600],
                source_url=_safe_url(p.get("source_url")),
                doc_status=p.get("doc_status"),
            )
    return list(seen.values())


def _safe_url(value: Any) -> str | None:
    """Only pass through plain https URLs reported by a service (never javascript:, data:, etc.)."""
    if not isinstance(value, str) or len(value) > 500:
        return None
    parsed = urlparse(value)
    return value if parsed.scheme == "https" and parsed.netloc and not parsed.username else None


def _text(source: dict[str, Any], key: str) -> str | None:
    value = source.get(key)
    return str(value)[:300] if value is not None else None


def collect_sources(executions: list[ToolExecution], server_names: dict[str, str]) -> list[SourceRef]:
    refs: dict[tuple[str, str], SourceRef] = {}
    for ex in executions:
        if ex.status is not ToolStatus.SUCCESS or not ex.server_id or not ex.tool_name:
            continue
        source: dict[str, Any] = (ex.data or {}).get("source") or {}
        stale = source.get("stale")
        refs[(ex.server_id, ex.tool_name)] = SourceRef(
            server_id=ex.server_id,
            server_name=server_names.get(ex.server_id, ex.server_id),
            tool=ex.tool_name,
            mode=_text(source, "mode"),
            provider=_text(source, "provider"),
            source_url=_safe_url(source.get("source_url")),
            retrieved_at=_text(source, "retrieved_at"),
            data_as_of=_text(source, "data_as_of"),
            stale=stale if isinstance(stale, bool) else None,
            staleness_reason=_text(source, "staleness_reason"),
            note=_text(source, "note"),
        )
    return list(refs.values())


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'(*-])|\n+")
_NUMBER = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)(?![\w])")


def _numbers_supported(answer: str, citations: list[Citation]) -> tuple[int, list[str]]:
    """Numbers stated next to a citation must occur in a cited passage from that page."""
    checked = 0
    unsupported: list[str] = []
    for sentence in _SENTENCE.split(answer):
        refs = list(_REF.finditer(sentence))
        if not refs:
            continue
        pages = {int(m.group(2)) for m in refs}
        evidence = " ".join(c.excerpt for c in citations if c.page in pages)
        body = _BARE_PAGE.sub("", _REF.sub("", sentence))  # page references are not claims
        for m in _NUMBER.finditer(body):
            value = m.group(1)
            checked += 1
            if not re.search(rf"(?<![\w.]){re.escape(value)}(?![\w])", evidence):
                unsupported.append(value)
    return checked, unsupported


def verify_citations(answer: str, citations: list[Citation]) -> CitationCheck:
    """Every ``[Title, p. N]`` and bare ``p. N`` in the answer must match a retrieved passage, and numbers in
    cited sentences must appear in the cited passages (see ``CitationCheck`` for what is not verified)."""
    pages = {c.page for c in citations}
    pairs = {(_norm(c.document_title), c.page) for c in citations}
    unsupported: list[str] = []
    checked = 0
    for m in _REF.finditer(answer):
        checked += 1
        title, page = _norm(m.group(1)), int(m.group(2))
        if not any((t == title or title in t or t in title) and p == page for t, p in pairs):
            unsupported.append(m.group(0))
    stripped = _REF.sub("", answer)
    for m in _BARE_PAGE.finditer(stripped):
        checked += 1
        if int(m.group(1)) not in pages:
            unsupported.append(m.group(0))
    numbers_checked, unsupported_numbers = _numbers_supported(answer, citations)
    return CitationCheck(
        checked=checked,
        unsupported=unsupported,
        numbers_checked=numbers_checked,
        unsupported_numbers=unsupported_numbers,
    )
