"""Qdrant-backed chunk index for academic documents.

Works against a Qdrant server (``QDRANT_URL``), an embedded on-disk store
(``QDRANT_PATH``) or an in-memory store (``:memory:``, used by tests).
"""

from __future__ import annotations

import uuid
import warnings
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from qdrant_client import QdrantClient, models

from .chunking import Chunk


@dataclass(frozen=True)
class SearchHit:
    score: float
    payload: dict[str, Any]


@dataclass(frozen=True)
class IndexedDocument:
    source_filename: str
    document_title: str
    document_version: str
    ingested_at: str
    pages: int
    chunks: int


def make_client(url: str | None, path: str | None, api_key: str | None = None) -> QdrantClient:
    if url:
        return QdrantClient(url=url, api_key=api_key, timeout=10)
    return QdrantClient(path=path) if path and path != ":memory:" else QdrantClient(":memory:")


class HandbookIndex:
    def __init__(self, client: QdrantClient, collection: str, dim: int, embedding_model: str) -> None:
        self.client = client
        self.collection = collection
        self.dim = dim
        self.embedding_model = embedding_model

    def ensure_collection(self) -> bool:
        """Create the collection if needed. Returns True if it was (re)created.

        If the existing collection was built with a different vector size the
        index is rebuilt, because vectors from different embedders are not comparable.
        """
        if self.client.collection_exists(self.collection):
            info = self.client.get_collection(self.collection)
            vectors = info.config.params.vectors
            size = vectors.size if isinstance(vectors, models.VectorParams) else None
            if size == self.dim:
                return False
            self.client.delete_collection(self.collection)
        self.client.create_collection(
            self.collection, vectors_config=models.VectorParams(size=self.dim, distance=models.Distance.COSINE)
        )
        with warnings.catch_warnings():  # local mode warns that payload indexes are no-ops
            warnings.simplefilter("ignore", UserWarning)
            for field in ("source_filename", "section", "doc_id"):
                self.client.create_payload_index(self.collection, field, models.PayloadSchemaType.KEYWORD)
        return True

    @staticmethod
    def _source_filter(filename: str) -> models.Filter:
        return models.Filter(
            must=[models.FieldCondition(key="source_filename", match=models.MatchValue(value=filename))]
        )

    def all_payloads(self) -> list[dict[str, Any]]:
        payloads: list[dict[str, Any]] = []
        offset: Any = None
        while True:
            points, offset = self.client.scroll(
                self.collection, limit=256, offset=offset, with_payload=True, with_vectors=False
            )
            payloads.extend(p.payload or {} for p in points)
            if offset is None:
                return payloads

    def versions_for_source(self, filename: str) -> set[tuple[str, str]]:
        """Return {(document_version, embedding_model)} currently indexed for a file."""
        points, _ = self.client.scroll(
            self.collection, scroll_filter=self._source_filter(filename), limit=1000, with_payload=True
        )
        return {
            (str(p.payload["document_version"]), str(p.payload.get("embedding_model"))) for p in points if p.payload
        }

    def delete_source(self, filename: str) -> None:
        self.client.delete(self.collection, points_selector=models.FilterSelector(filter=self._source_filter(filename)))

    def upsert_chunks(self, chunks: list[Chunk], vectors: list[list[float]], page_count: int) -> None:
        ingested_at = datetime.now(UTC).isoformat(timespec="seconds")
        points = [
            models.PointStruct(
                id=str(uuid.uuid5(uuid.NAMESPACE_URL, chunk.chunk_id)),
                vector=vector,
                payload={
                    **asdict(chunk),
                    "ingested_at": ingested_at,
                    "embedding_model": self.embedding_model,
                    "page_count": page_count,
                },
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        if points:
            self.client.upsert(self.collection, points=points, wait=True)

    def search(self, vector: list[float], top_k: int) -> list[SearchHit]:
        res = self.client.query_points(self.collection, query=vector, limit=top_k, with_payload=True)
        return [SearchHit(score=float(p.score), payload=p.payload or {}) for p in res.points]

    def section_chunks(self, doc_id: str, section: str) -> list[dict[str, Any]]:
        flt = models.Filter(
            must=[
                models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id)),
                models.FieldCondition(key="section", match=models.MatchValue(value=section)),
            ]
        )
        points, _ = self.client.scroll(self.collection, scroll_filter=flt, limit=200, with_payload=True)
        payloads = [p.payload or {} for p in points]
        return sorted(payloads, key=lambda p: (p["page_number"], p["chunk_index"]))

    def documents(self) -> list[IndexedDocument]:
        grouped: dict[str, dict[str, Any]] = {}
        for p in self.all_payloads():
            entry = grouped.setdefault(
                p["source_filename"],
                {
                    "source_filename": p["source_filename"],
                    "document_title": p["document_title"],
                    "document_version": p["document_version"],
                    "ingested_at": p["ingested_at"],
                    "pages": int(p.get("page_count", 0)),
                    "chunks": 0,
                },
            )
            entry["chunks"] += 1
        return [IndexedDocument(**v) for v in sorted(grouped.values(), key=lambda d: d["source_filename"])]
