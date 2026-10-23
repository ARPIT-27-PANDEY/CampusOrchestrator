"""Collect citations and source metadata from tool results, and verify answer citations.

Citations shown to the user are built from what the retrieval tool actually
returned, not from model text, so the UI can never display a fabricated reference.
``verify_citations`` additionally flags page references in the answer that no
retrieved passage supports.
"""

from __future__ import annotations

import re
from typing import Any

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
            )
    return list(seen.values())


def collect_sources(executions: list[ToolExecution], server_names: dict[str, str]) -> list[SourceRef]:
    refs: dict[tuple[str, str], SourceRef] = {}
    for ex in executions:
        if ex.status is not ToolStatus.SUCCESS or not ex.server_id or not ex.tool_name:
            continue
        source: dict[str, Any] = (ex.data or {}).get("source") or {}
        refs[(ex.server_id, ex.tool_name)] = SourceRef(
            server_id=ex.server_id,
            server_name=server_names.get(ex.server_id, ex.server_id),
            tool=ex.tool_name,
            mode=source.get("mode"),
            provider=source.get("provider"),
            data_as_of=source.get("data_as_of"),
            stale=source.get("stale"),
        )
    return list(refs.values())


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def verify_citations(answer: str, citations: list[Citation]) -> CitationCheck:
    """Every ``[Title, p. N]`` and bare ``p. N`` in the answer must match a retrieved passage."""
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
    return CitationCheck(checked=checked, unsupported=unsupported)
