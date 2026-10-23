"""Retrieval logic behind the academics MCP tools."""

from __future__ import annotations

import re
from typing import Any

from .config import AcademicsSettings
from .embeddings import Embedder, build_embedder, tokenize
from .index import HandbookIndex, make_client
from .models import HandbookSearchResult, IndexedDocumentInfo, Passage, PolicyDetails, SourceInfo

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


def sanitize_excerpt(text: str) -> tuple[str, bool]:
    cleaned, n = _INJECTION.subn(f" {REDACTION_MARK} ", text)
    return re.sub(r"\s{2,}", " ", cleaned).strip(), n > 0


def build_index_and_embedder(settings: AcademicsSettings) -> tuple[HandbookIndex, Embedder]:
    embedder = build_embedder(settings.embedding_provider, settings.embedding_model)
    client = make_client(settings.qdrant_url, settings.qdrant_path, settings.qdrant_api_key)
    index = HandbookIndex(client, settings.collection, embedder.dim, embedder.name)
    return index, embedder


class HandbookService:
    def __init__(self, index: HandbookIndex, embedder: Embedder, settings: AcademicsSettings) -> None:
        self.index = index
        self.embedder = embedder
        self.settings = settings

    def source_info(self) -> SourceInfo:
        docs = [
            IndexedDocumentInfo(
                title=d.document_title,
                source_filename=d.source_filename,
                document_version=d.document_version,
                ingested_at=d.ingested_at,
                pages=d.pages,
                chunks=d.chunks,
            )
            for d in self.index.documents()
        ]
        return SourceInfo(
            mode="demo" if self.settings.data_mode == "demo" else "imported",
            provider="qdrant",
            embedding_model=self.embedder.name,
            index_freshness="Snapshot of the PDFs at ingestion time (see ingested_at); not a live policy feed.",
            documents=docs,
        )

    @staticmethod
    def _passage(payload: dict[str, Any], score: float) -> Passage:
        excerpt, removed = sanitize_excerpt(str(payload["text"]))
        return Passage(
            citation_id=str(payload["chunk_id"]),
            document_title=str(payload["document_title"]),
            source_filename=str(payload["source_filename"]),
            document_version=str(payload["document_version"]),
            page=int(payload["page_number"]),
            section=str(payload["section"]),
            excerpt=excerpt,
            score=round(score, 4),
            untrusted_instructions_removed=removed,
        )

    def _relevant(self, query: str, payload: dict[str, Any], score: float) -> bool:
        """Require a minimum similarity AND at least one shared content term.

        The lexical guard stops semantically-unrelated questions from returning
        the "least bad" passage as if it were evidence.
        """
        if score < self.settings.min_score:
            return False
        q_terms = set(tokenize(query))
        doc_terms = set(tokenize(f"{payload.get('section', '')} {payload.get('text', '')}"))
        return bool(q_terms & doc_terms)

    @staticmethod
    def _has_evidence(p: Passage) -> bool:
        """A passage that is nothing but redacted instructions carries no evidence."""
        return len(p.excerpt.replace(REDACTION_MARK, "").strip(" .:()")) >= 20

    def search(self, query: str, top_k: int) -> HandbookSearchResult:
        hits = self.index.search(self.embedder.embed_query(query), top_k + 2)
        relevant = [self._passage(h.payload, h.score) for h in hits if self._relevant(query, h.payload, h.score)]
        passages = [p for p in relevant if self._has_evidence(p)][:top_k]
        dropped = len(relevant) - len([p for p in relevant if self._has_evidence(p)])
        message = None if passages else INSUFFICIENT
        if dropped:
            message = f"{dropped} matching passage(s) contained only instruction-like text and were withheld."
        return HandbookSearchResult(
            query=query,
            found=bool(passages),
            passages=passages,
            message=message,
            source=self.source_info(),
        )

    def policy(self, policy_name: str) -> PolicyDetails:
        hits = self.index.search(self.embedder.embed_query(f"{policy_name} policy"), 5)
        best = next((h for h in hits if self._relevant(policy_name, h.payload, h.score)), None)
        if best is None:
            return PolicyDetails(policy_name=policy_name, found=False, message=INSUFFICIENT, source=self.source_info())
        section = str(best.payload["section"])
        chunks = self.index.section_chunks(str(best.payload["doc_id"]), section)
        passages = [self._passage(c, best.score if c["chunk_id"] == best.payload["chunk_id"] else 0.0) for c in chunks]
        return PolicyDetails(
            policy_name=policy_name,
            found=True,
            section=section,
            document_title=str(best.payload["document_title"]),
            pages=sorted({p.page for p in passages}),
            passages=passages[:12],
            source=self.source_info(),
        )
