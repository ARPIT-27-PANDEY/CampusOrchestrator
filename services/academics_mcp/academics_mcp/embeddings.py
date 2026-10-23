"""Embedding providers.

``HashingEmbedder`` is a dependency-free, deterministic embedder (signed feature
hashing over stemmed unigrams and bigrams). It needs no model download, which
keeps tests and offline demos reproducible. It is lexical, not semantic: for
better paraphrase recall set ``EMBEDDING_PROVIDER=fastembed`` (BAAI/bge-small-en-v1.5
via the optional ``fastembed`` extra; the model is downloaded on first use).
"""

from __future__ import annotations

import hashlib
import itertools
import math
import re
from typing import Protocol

_TOKEN = re.compile(r"[a-z0-9]+")
_STOP = {
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does", "for", "from", "how", "i", "if", "in",
    "is", "it", "me", "my", "of", "on", "or", "that", "the", "this", "to", "what", "when", "which", "who", "will",
    "with", "you", "your", "tell", "about", "there", "any", "should", "must", "much",
}  # fmt: skip


def _stem(token: str) -> str:
    for suffix in ("ations", "ation", "ments", "ment", "ings", "ing", "ies", "es", "ed", "s"):
        if len(token) > len(suffix) + 2 and token.endswith(suffix):
            return token[: -len(suffix)] + ("y" if suffix == "ies" else "")
    return token


def tokenize(text: str) -> list[str]:
    return [_stem(t) for t in _TOKEN.findall(text.lower()) if t not in _STOP]


class Embedder(Protocol):
    name: str
    dim: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class HashingEmbedder:
    def __init__(self, dim: int = 512) -> None:
        self.dim = dim
        self.name = f"hashing-v1-{dim}"

    def _bucket(self, feature: str) -> tuple[int, float]:
        digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
        value = int.from_bytes(digest, "little")
        return value % self.dim, 1.0 if (value >> 63) & 1 else -1.0

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        tokens = tokenize(text)
        features = tokens + [f"{a}_{b}" for a, b in itertools.pairwise(tokens)]
        for feat in features:
            idx, sign = self._bucket(feat)
            vec[idx] += sign * (1.5 if "_" in feat else 1.0)
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm else vec

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class FastEmbedEmbedder:  # pragma: no cover - requires optional dependency and model download
    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        from fastembed import TextEmbedding

        self._model = TextEmbedding(model_name=model_name)
        self.name = f"fastembed:{model_name}"
        self.dim = len(next(iter(self._model.embed(["dimension probe"]))))

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [list(map(float, v)) for v in self._model.embed(texts)]

    def embed_query(self, text: str) -> list[float]:
        return [float(x) for x in next(iter(self._model.query_embed(text)))]


def build_embedder(provider: str, model: str | None = None) -> Embedder:
    if provider == "hashing":
        return HashingEmbedder()
    if provider == "fastembed":
        return FastEmbedEmbedder(model or "BAAI/bge-small-en-v1.5")
    raise ValueError(f"Unsupported EMBEDDING_PROVIDER '{provider}' (expected 'hashing' or 'fastembed').")
