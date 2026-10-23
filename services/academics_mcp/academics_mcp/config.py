"""Environment-based configuration for the academics MCP server."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_HANDBOOK_DIR = Path(__file__).resolve().parents[1] / "data" / "handbooks"


@dataclass(frozen=True)
class AcademicsSettings:
    handbook_dir: Path = DEFAULT_HANDBOOK_DIR
    qdrant_url: str | None = None
    qdrant_path: str | None = ":memory:"
    qdrant_api_key: str | None = None
    collection: str = "campus_handbooks"
    embedding_provider: str = "hashing"
    embedding_model: str | None = None
    min_score: float = 0.12
    auto_ingest: bool = True
    data_mode: str = "demo"  # demo fixtures vs operator-supplied documents

    @classmethod
    def from_env(cls) -> AcademicsSettings:
        return cls(
            handbook_dir=Path(os.getenv("HANDBOOK_DIR", str(DEFAULT_HANDBOOK_DIR))),
            qdrant_url=os.getenv("QDRANT_URL") or None,
            qdrant_path=os.getenv("QDRANT_PATH", ":memory:"),
            qdrant_api_key=os.getenv("QDRANT_API_KEY") or None,
            collection=os.getenv("QDRANT_COLLECTION", "campus_handbooks"),
            embedding_provider=os.getenv("EMBEDDING_PROVIDER", "hashing").lower(),
            embedding_model=os.getenv("EMBEDDING_MODEL") or None,
            min_score=float(os.getenv("RAG_MIN_SCORE", "0.12")),
            auto_ingest=os.getenv("AUTO_INGEST", "true").lower() in ("1", "true", "yes"),
            data_mode=os.getenv("ACADEMICS_DATA_MODE", "demo").lower(),
        )
