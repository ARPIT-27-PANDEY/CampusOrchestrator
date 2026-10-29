"""Semantic (embedding) ranking for the campus catalogue, fused with keyword tiers.

Each book is embedded once from its title, subjects, discipline and authors. A query is embedded and
scored by cosine similarity. A book counts only if it clears two gates: an absolute similarity
(``min_score``) and a per-query z-score (``min_z``: how far it stands above this query's similarity to
the whole catalogue). Small embedding models give unrelated pairs fairly high cosine values, so the
second gate is what lets an unrelated query still return an honest "no match". The semantic ranking is fused with
the keyword ranking by Reciprocal Rank Fusion (RRF, k = 60), so books found by both rank first.

Embedders: ``fastembed`` (BAAI/bge-small-en-v1.5, optional extra, model downloaded on first use) is
semantic. ``hashing`` is a dependency-free lexical baseline for offline runs and benchmarks; it is not
semantic. A requested embedder that is not installed raises; it is never silently replaced.
"""

from __future__ import annotations

import hashlib
import itertools
import math
import os
import re
from dataclasses import dataclass
from typing import Any, Protocol

RRF_K = 60
DEFAULT_MODEL = "BAAI/bge-small-en-v1.5"
# Gates per embedding space, chosen on the dev split of evals/datasets/library_search_v1.yaml only
# (python -m evals.run_library_search --tune; see docs/evaluation.md). Override with
# LIBRARY_SEMANTIC_MIN_SCORE / LIBRARY_SEMANTIC_MIN_Z.
DEFAULT_MIN_SCORE = {"fastembed": 0.68, "hashing": 0.60}
DEFAULT_MIN_Z = {"fastembed": 1.5, "hashing": 4.0}
MIN_POOL_FOR_Z = 20  # with fewer candidates (heavy filtering) the z-score is not meaningful


class Embedder(Protocol):
    name: str

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class EmbedderUnavailableError(RuntimeError):
    """The requested embedding backend is not installed. Never silently replaced by another one."""


_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {"a", "an", "and", "about", "any", "book", "books", "for", "in", "of", "on", "the", "to", "with"}


def _stem(token: str) -> str:
    for suffix in ("ations", "ation", "ments", "ment", "ings", "ing", "ies", "es", "ed", "s"):
        if len(token) > len(suffix) + 2 and token.endswith(suffix):
            return token[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return token


class HashingEmbedder:
    """Signed feature hashing over stemmed unigrams and bigrams: lexical, offline, deterministic."""

    def __init__(self, dim: int = 512) -> None:
        self.dim = dim
        self.name = f"hashing-v1-{dim}"

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = [_stem(t) for t in _TOKEN.findall(text.lower()) if t not in _STOP]
        for feat in tokens + [f"{a}_{b}" for a, b in itertools.pairwise(tokens)]:
            value = int.from_bytes(hashlib.blake2b(feat.encode(), digest_size=8).digest(), "little")
            vec[value % self.dim] += (1.0 if (value >> 63) & 1 else -1.0) * (1.5 if "_" in feat else 1.0)
        return vec

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class FastEmbedEmbedder:  # pragma: no cover - requires the optional dependency and a model download
    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        try:
            from fastembed import TextEmbedding
        except ImportError as exc:
            raise EmbedderUnavailableError(
                "LIBRARY_SEARCH_MODE=hybrid with LIBRARY_EMBEDDER=fastembed needs the optional dependency: "
                "pip install 'campusos-library-mcp[fastembed]' (downloads the ONNX model, ~130 MB, on first use)."
            ) from exc
        self._model = TextEmbedding(model_name=model_name)
        self.name = f"fastembed:{model_name}"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self._model.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return [float(x) for x in next(iter(self._model.query_embed(text)))]


def build_embedder(name: str, model: str | None = None) -> Embedder:
    if name == "fastembed":
        return FastEmbedEmbedder(model or DEFAULT_MODEL)
    if name == "hashing":
        return HashingEmbedder()
    raise ValueError(f"Unsupported LIBRARY_EMBEDDER '{name}' (expected 'fastembed' or 'hashing').")


def _unit(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm else vec


def book_text(book: dict[str, Any]) -> str:
    """The text a book is embedded from: catalogue metadata only (no synthetic circulation fields)."""
    parts = [book["title"]]
    if book.get("subjects"):
        parts.append("Subjects: " + ", ".join(book["subjects"]))
    if book.get("discipline"):
        parts.append(f"Discipline: {book['discipline']}")
    if book.get("authors"):
        parts.append("By " + ", ".join(book["authors"]))
    return ". ".join(parts)


@dataclass
class SemanticIndex:
    """Book vectors (unit length) keyed by book_id, plus the threshold for counting a match."""

    embedder: Embedder
    vectors: dict[str, list[float]]
    min_score: float
    min_z: float = 0.0

    @classmethod
    def build(
        cls, embedder: Embedder, books: list[dict[str, Any]], min_score: float, min_z: float = 0.0
    ) -> SemanticIndex:
        vectors = embedder.embed_documents([book_text(b) for b in books])
        unit = {b["book_id"]: _unit(v) for b, v in zip(books, vectors, strict=True)}
        return cls(embedder, unit, min_score, min_z)

    @property
    def label(self) -> str:
        return f"hybrid:{self.embedder.name}"

    def scores(self, query: str, book_ids: list[str]) -> list[tuple[str, float]]:
        """All candidate books with their cosine similarity, best first (no threshold applied)."""
        q = _unit(self.embedder.embed_query(query))
        out = [(bid, sum(a * b for a, b in zip(q, self.vectors[bid], strict=True))) for bid in book_ids]
        out.sort(key=lambda x: (-x[1], x[0]))
        return out

    def rank(self, query: str, book_ids: list[str]) -> list[tuple[str, float]]:
        scored = self.scores(query, book_ids)
        keep = [(bid, s) for bid, s in scored if s >= self.min_score]
        if self.min_z > 0 and len(scored) >= MIN_POOL_FOR_Z:
            values = [s for _, s in scored]
            mean = sum(values) / len(values)
            sd = math.sqrt(sum((v - mean) ** 2 for v in values) / len(values))
            keep = [(bid, s) for bid, s in keep if sd and (s - mean) / sd >= self.min_z]
        return keep


def rrf_fuse(*rankings: list[str], k: int = RRF_K) -> list[str]:
    """Fuse ranked id lists: score = sum of 1 / (k + rank). Ties break on id for determinism."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, bid in enumerate(ranking, start=1):
            scores[bid] = scores.get(bid, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda b: (-scores[b], b))


def semantic_from_env(books: list[dict[str, Any]]) -> SemanticIndex | None:
    """``LIBRARY_SEARCH_MODE=hybrid`` builds the index; ``keyword`` (default) returns None."""
    mode = os.getenv("LIBRARY_SEARCH_MODE", "keyword").lower()
    if mode == "keyword":
        return None
    if mode != "hybrid":
        raise ValueError(f"Unsupported LIBRARY_SEARCH_MODE '{mode}' (expected 'keyword' or 'hybrid').")
    name = os.getenv("LIBRARY_EMBEDDER", "fastembed").lower()
    min_score = float(os.getenv("LIBRARY_SEMANTIC_MIN_SCORE") or DEFAULT_MIN_SCORE.get(name, 0.5))
    min_z = float(os.getenv("LIBRARY_SEMANTIC_MIN_Z") or DEFAULT_MIN_Z.get(name, 0.0))
    embedder = build_embedder(name, os.getenv("LIBRARY_EMBEDDING_MODEL") or None)
    return SemanticIndex.build(embedder, books, min_score, min_z)
