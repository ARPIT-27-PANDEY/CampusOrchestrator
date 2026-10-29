"""Environment-based configuration for the academics MCP server."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
OFFICIAL_DOC_DIR = DATA_DIR / "iitr"  # official IIT Roorkee PDFs (fetched via academics_mcp.sources)
DEMO_HANDBOOK_DIR = DATA_DIR / "handbooks"  # fictional demo handbooks (tests and the v1 evaluation)
DEFAULT_HANDBOOK_DIR = OFFICIAL_DOC_DIR
DEFAULT_MANIFEST = DATA_DIR / "sources" / "iitr_sources.yaml"
# Relevance thresholds per embedding space (cosine scales differ). fastembed's value was chosen on the dev
# split of evals/datasets/retrieval_iitr_v1.yaml; hashing keeps its original 0.12 (see docs/evaluation.md).
DEFAULT_MIN_SCORE = {"hashing": 0.12, "fastembed": 0.72}


@dataclass(frozen=True)
class AcademicsSettings:
    handbook_dir: Path = DEFAULT_HANDBOOK_DIR
    manifest_path: Path | None = field(default=DEFAULT_MANIFEST)
    qdrant_url: str | None = None
    qdrant_path: str | None = ":memory:"
    qdrant_api_key: str | None = None
    collection: str = "campus_handbooks"
    embedding_provider: str = "hashing"  # hashing | fastembed
    embedding_model: str | None = None
    retrieval_mode: str = "dense"  # dense | hybrid (dense + BM25-style lexical, fused with RRF)
    min_score: float = 0.12
    bm25_min_score: float = 6.0  # hybrid mode: lexical evidence threshold (tuned on the dev split)
    auto_ingest: bool = True
    data_mode: str = "auto"  # auto: official manifest docs -> imported, others -> demo

    @classmethod
    def for_embedder(cls, provider: str, **kw: object) -> AcademicsSettings:
        """Settings with the embedder-specific default relevance threshold."""
        return cls(embedding_provider=provider, min_score=DEFAULT_MIN_SCORE.get(provider, 0.12), **kw)  # type: ignore[arg-type]

    @classmethod
    def from_env(cls) -> AcademicsSettings:
        manifest = os.getenv("SOURCE_MANIFEST")
        provider = os.getenv("EMBEDDING_PROVIDER", "hashing").lower()
        return cls(
            handbook_dir=Path(os.getenv("HANDBOOK_DIR", str(DEFAULT_HANDBOOK_DIR))),
            manifest_path=Path(manifest) if manifest else (None if manifest == "" else DEFAULT_MANIFEST),
            qdrant_url=os.getenv("QDRANT_URL") or None,
            qdrant_path=os.getenv("QDRANT_PATH", ":memory:"),
            qdrant_api_key=os.getenv("QDRANT_API_KEY") or None,
            collection=os.getenv("QDRANT_COLLECTION", "campus_handbooks"),
            embedding_provider=provider,
            embedding_model=os.getenv("EMBEDDING_MODEL") or None,
            retrieval_mode=os.getenv("RETRIEVAL_MODE", "dense").lower(),
            min_score=float(os.getenv("RAG_MIN_SCORE") or DEFAULT_MIN_SCORE.get(provider, 0.12)),
            bm25_min_score=float(os.getenv("RAG_BM25_MIN_SCORE", "6.0")),
            auto_ingest=os.getenv("AUTO_INGEST", "true").lower() in ("1", "true", "yes"),
            data_mode=os.getenv("ACADEMICS_DATA_MODE", "auto").lower(),
        )
