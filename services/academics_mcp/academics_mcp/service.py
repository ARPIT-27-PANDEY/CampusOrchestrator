"""Retrieval logic behind the academics MCP tools."""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from .config import AcademicsSettings
from .embeddings import Embedder, build_embedder, tokenize
from .index import HandbookIndex, SearchHit, make_client
from .models import HandbookSearchResult, IndexedDocumentInfo, Passage, PolicyDetails, SourceInfo
from .sources import Manifest, SourceError, load_manifest

log = logging.getLogger("academics_mcp.service")

# Instruction-like text inside retrieved documents is data, never instructions.
# These patterns are defence-in-depth; the orchestrator also wraps all tool output as untrusted.
_INJECTION = re.compile(
    r"[^.]*\b(ignore (all |any )?(previous|prior|above) instructions|disregard (the |all )?(system|previous)|"
    r"system prompt|reveal (your|the|any) (system|api|secret|key)|api keys?|you are now|"
    r"call every available tool|notice to ai assistants?)\b[^.]*\.?",
    re.IGNORECASE,
)
INSUFFICIENT = "No passage in the indexed academic documents sufficiently matches this question."
REDACTION_MARK = "[instruction-like text removed]"
SUPERSEDED_PENALTY = 0.85  # superseded documents rank below current ones at similar relevance


def sanitize_excerpt(text: str) -> tuple[str, bool]:
    cleaned, n = _INJECTION.subn(f" {REDACTION_MARK} ", text)
    return re.sub(r"\s{2,}", " ", cleaned).strip(), n > 0


def collection_name(base: str, embedder_name: str) -> str:
    """One collection per embedding space, so vectors from different embedders never mix."""
    slug = re.sub(r"[^a-z0-9]+", "_", embedder_name.lower()).strip("_")
    return f"{base}__{slug}"


def load_manifest_for(settings: AcademicsSettings) -> Manifest | None:
    if settings.manifest_path is None or not settings.manifest_path.exists():
        return None
    try:
        return load_manifest(settings.manifest_path)
    except (SourceError, OSError, ValueError) as exc:
        log.error("Source manifest %s is invalid: %s", settings.manifest_path, exc)
        raise


def build_index_and_embedder(settings: AcademicsSettings) -> tuple[HandbookIndex, Embedder]:
    embedder = build_embedder(settings.embedding_provider, settings.embedding_model)
    client = make_client(settings.qdrant_url, settings.qdrant_path, settings.qdrant_api_key)
    index = HandbookIndex(client, collection_name(settings.collection, embedder.name), embedder.dim, embedder.name)
    return index, embedder


class HandbookService:
    def __init__(
        self,
        index: HandbookIndex,
        embedder: Embedder,
        settings: AcademicsSettings,
        manifest: Manifest | None = None,
        not_indexed: list[str] | None = None,
    ) -> None:
        self.index = index
        self.embedder = embedder
        self.settings = settings
        self.manifest = manifest
        self.not_indexed = not_indexed or []
        self._titles = {d.id: d.title for d in manifest.documents} if manifest else {}
        self._lexical: Any = None  # built lazily for hybrid retrieval

    def source_info(self) -> SourceInfo:
        docs = [
            IndexedDocumentInfo(
                title=d.document_title,
                source_filename=d.source_filename,
                document_version=d.document_version,
                ingested_at=d.ingested_at,
                pages=d.pages,
                chunks=d.chunks,
                origin="official" if d.origin == "official" else "demo",
                source_url=d.source_url,
                status=d.doc_status,
                issued=d.issued,
            )
            for d in self.index.documents()
        ]
        any_demo = any(d.origin == "demo" for d in docs) or self.settings.data_mode == "demo"
        return SourceInfo(
            mode="demo" if any_demo else "imported",
            provider="qdrant",
            embedding_model=self.embedder.name,
            retrieval=self.settings.retrieval_mode,
            index_freshness=(
                "Snapshot of the PDFs at ingestion time (see ingested_at). Official documents are copies of "
                "iitr.ac.in PDFs; the official URL is authoritative. Not a live policy feed."
            ),
            retrieved_at=datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
            stale=None,
            staleness_reason="Newer notifications may exist on iitr.ac.in that have not been ingested.",
            documents=docs,
            not_indexed=self.not_indexed,
        )

    def _passage(self, payload: dict[str, Any], score: float) -> Passage:
        excerpt, removed = sanitize_excerpt(str(payload["text"]))
        official = bool(payload.get("source_id"))
        return Passage(
            citation_id=str(payload["chunk_id"]),
            document_title=str(payload.get("official_title") or payload["document_title"]),
            source_filename=str(payload["source_filename"]),
            document_version=str(payload["document_version"]),
            page=int(payload["page_number"]),
            section=str(payload["section"]),
            excerpt=excerpt,
            score=round(score, 4),
            untrusted_instructions_removed=removed,
            origin="official" if official else "demo",
            source_url=payload.get("source_url"),
            authority=payload.get("authority"),
            issued=payload.get("issued"),
            reference=payload.get("reference"),
            applies_to=list(payload.get("applies_to") or []),
            doc_status=payload.get("doc_status"),
            superseded_by=[self._titles.get(i, i) for i in payload.get("superseded_by") or []],
        )

    def _relevant(self, query: str, payload: dict[str, Any], score: float, min_score: float | None = None) -> bool:
        """Require a minimum similarity AND at least one shared content term.

        Dense mode: the cosine score must reach ``min_score``. Hybrid mode (RRF scores are rank-based):
        the chunk must reach ``min_score`` in the dense list OR ``bm25_min_score`` in the lexical list.
        The lexical guard stops semantically-unrelated questions from returning
        the "least bad" passage as if it were evidence.
        """
        if self.settings.retrieval_mode == "hybrid":
            dense = payload.get("_score_dense")
            bm25 = payload.get("_score_bm25")
            if not (
                (dense is not None and dense >= self.settings.min_score)
                or (bm25 is not None and bm25 >= self.settings.bm25_min_score)
            ):
                return False
        elif score < (self.settings.min_score if min_score is None else min_score):
            return False
        q_terms = set(tokenize(query))
        doc_terms = set(tokenize(f"{payload.get('section', '')} {payload.get('text', '')}"))
        return bool(q_terms & doc_terms)

    @staticmethod
    def _has_evidence(p: Passage) -> bool:
        """A passage that is nothing but redacted instructions carries no evidence."""
        return len(p.excerpt.replace(REDACTION_MARK, "").strip(" .:()")) >= 20

    # ------------------------------------------------------------------ retrieval
    def retrieve(self, query: str, top_k: int) -> list[SearchHit]:
        """Ranked candidate hits (before relevance filtering). Dense or hybrid per settings."""
        dense = self.index.search(self.embedder.embed_query(query), max(top_k + 2, 10))
        if self.settings.retrieval_mode != "hybrid":
            return dense
        from .hybrid import LexicalIndex, rrf_fuse

        if self._lexical is None:
            self._lexical = LexicalIndex.from_payloads(self.index.all_payloads())
        lexical = self._lexical.search(query, max(top_k + 2, 10))
        return rrf_fuse(dense, lexical, names=("dense", "bm25"))

    def invalidate_caches(self) -> None:
        self._lexical = None

    @staticmethod
    def _rank_key(p: Passage) -> float:
        return p.score * (SUPERSEDED_PENALTY if p.doc_status == "superseded" else 1.0)

    def _applicability(self, passages: list[Passage]) -> list[str]:
        notes: list[str] = []
        titles = {p.document_title for p in passages}
        for title in sorted(titles):
            p = next(x for x in passages if x.document_title == title)
            if p.doc_status == "superseded":
                newer = ", ".join(p.superseded_by) or "a newer document"
                present = any(t in titles for t in p.superseded_by)
                notes.append(
                    f"'{title}' is superseded by {newer}"
                    + ("; prefer the newer document where they differ." if present else
                       "; the newer document has no matching passage, so this text may no longer apply.")
                )  # fmt: skip
            scope = [a for a in p.applies_to if a != "all"]
            if scope:
                notes.append(f"'{title}' applies to: {', '.join(scope)} - not necessarily to every student.")
        return notes

    def search(self, query: str, top_k: int) -> HandbookSearchResult:
        hits = self.retrieve(query, top_k)
        min_score = 0.0 if self.settings.retrieval_mode == "hybrid" else None  # RRF scores are rank-based
        relevant = [
            self._passage(h.payload, h.score) for h in hits if self._relevant(query, h.payload, h.score, min_score)
        ]
        evidenced = [p for p in relevant if self._has_evidence(p)]
        titles = {p.document_title for p in evidenced}

        def order(p: Passage) -> tuple[int, float]:
            # A superseded passage whose successor was also retrieved always ranks after current ones.
            replaced = p.doc_status == "superseded" and any(t in titles for t in p.superseded_by)
            return (1 if replaced else 0, -self._rank_key(p))

        passages = sorted(evidenced, key=order)[:top_k]
        dropped = len(relevant) - len(evidenced)
        message = None if passages else INSUFFICIENT
        if dropped:
            message = f"{dropped} matching passage(s) contained only instruction-like text and were withheld."
        return HandbookSearchResult(
            query=query,
            found=bool(passages),
            passages=passages,
            message=message,
            applicability_notes=self._applicability(passages),
            source=self.source_info(),
        )

    def policy(self, policy_name: str) -> PolicyDetails:
        hits = self.retrieve(f"{policy_name} policy", 5)
        min_score = 0.0 if self.settings.retrieval_mode == "hybrid" else None
        candidates = [h for h in hits if self._relevant(policy_name, h.payload, h.score, min_score)]
        candidates.sort(
            key=lambda h: h.score * (SUPERSEDED_PENALTY if h.payload.get("doc_status") == "superseded" else 1.0),
            reverse=True,
        )
        best = candidates[0] if candidates else None
        if best is None:
            return PolicyDetails(policy_name=policy_name, found=False, message=INSUFFICIENT, source=self.source_info())
        section = str(best.payload["section"])
        chunks = self.index.section_chunks(str(best.payload["doc_id"]), section)
        passages = [self._passage(c, best.score if c["chunk_id"] == best.payload["chunk_id"] else 0.0) for c in chunks]
        top = passages[:12]
        return PolicyDetails(
            policy_name=policy_name,
            found=True,
            section=section,
            document_title=top[0].document_title if top else str(best.payload["document_title"]),
            pages=sorted({p.page for p in passages}),
            passages=top,
            applicability_notes=self._applicability(top),
            source=self.source_info(),
        )
