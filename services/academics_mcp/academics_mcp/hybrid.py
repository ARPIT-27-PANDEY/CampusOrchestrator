"""Lexical (BM25) retrieval and Reciprocal Rank Fusion for hybrid search.

Design: dense retrieval (hashing or FastEmbed vectors in Qdrant) and lexical BM25 retrieval
run independently over the *same chunks*; their rankings are fused with RRF
(score = sum over lists of 1 / (k + rank)), k = 60 as in Cormack et al. (2009).
The BM25 index is built in memory from the chunk payloads already stored in Qdrant, so the
Qdrant collection and its payloads are unchanged and the dense baseline stays reproducible.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Any

from .embeddings import tokenize
from .index import SearchHit

RRF_K = 60


@dataclass
class _Doc:
    payload: dict[str, Any]
    tf: Counter[str]
    length: int


class LexicalIndex:
    def __init__(self, docs: list[_Doc], k1: float = 1.2, b: float = 0.75) -> None:
        self.docs = docs
        self.k1 = k1
        self.b = b
        self.avgdl = sum(d.length for d in docs) / len(docs) if docs else 0.0
        df: Counter[str] = Counter()
        for d in docs:
            df.update(d.tf.keys())
        n = len(docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    @classmethod
    def from_payloads(cls, payloads: list[dict[str, Any]]) -> LexicalIndex:
        docs = []
        for p in payloads:
            tokens = tokenize(f"{p.get('section', '')} {p.get('text', '')}")
            docs.append(_Doc(payload=p, tf=Counter(tokens), length=len(tokens)))
        return cls(docs)

    def score(self, query_terms: list[str], doc: _Doc) -> float:
        s = 0.0
        for t in query_terms:
            f = doc.tf.get(t, 0)
            if not f:
                continue
            norm = f + self.k1 * (1 - self.b + self.b * doc.length / (self.avgdl or 1))
            s += self.idf.get(t, 0.0) * f * (self.k1 + 1) / norm
        return s

    def search(self, query: str, top_k: int) -> list[SearchHit]:
        terms = tokenize(query)
        scored = [(self.score(terms, d), d) for d in self.docs]
        scored = [(s, d) for s, d in scored if s > 0]
        scored.sort(key=lambda x: (-x[0], str(x[1].payload.get("chunk_id"))))
        return [SearchHit(score=s, payload=d.payload) for s, d in scored[:top_k]]


def rrf_fuse(*rankings: list[SearchHit], k: int = RRF_K, names: tuple[str, ...] = ()) -> list[SearchHit]:
    """Fuse ranked lists by chunk_id. The fused score is the RRF sum (rank-based, not a similarity).

    With ``names``, each fused payload is a copy annotated with ``_score_<name>`` holding that list's
    original score, so relevance gates can still use real similarity/BM25 values after fusion.
    """
    scores: dict[str, float] = {}
    payloads: dict[str, dict[str, Any]] = {}
    for i, ranking in enumerate(rankings):
        label = names[i] if i < len(names) else None
        for rank, hit in enumerate(ranking, start=1):
            cid = str(hit.payload.get("chunk_id"))
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (k + rank)
            entry = payloads.setdefault(cid, dict(hit.payload))
            if label:
                entry[f"_score_{label}"] = hit.score
    order = sorted(scores, key=lambda c: (-scores[c], c))
    return [SearchHit(score=scores[c], payload=payloads[c]) for c in order]
