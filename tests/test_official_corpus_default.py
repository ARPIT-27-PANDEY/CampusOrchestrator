"""Without overrides the Academics server serves the official IIT Roorkee corpus, labelled 'imported'."""

from __future__ import annotations

from pathlib import Path

import pytest

from .conftest import ROOT

OFFICIAL_DIR = ROOT / "services" / "academics_mcp" / "data" / "iitr"


@pytest.mark.skipif(not any(Path(OFFICIAL_DIR).glob("*.pdf")), reason="official PDFs not fetched")
def test_default_settings_index_official_documents_only() -> None:
    from academics_mcp.config import AcademicsSettings
    from academics_mcp.server import build_service

    svc = build_service(AcademicsSettings(qdrant_path=":memory:"))
    info = svc.source_info()
    assert info.mode == "imported"
    assert info.documents and all(d.origin == "official" for d in info.documents)
    assert all(d.source_url and d.source_url.startswith("https://iitr.ac.in/") for d in info.documents)
    # Scanned PDFs are disclosed, not silently counted as covered.
    assert any("needs OCR" in n for n in info.not_indexed)
    result = svc.search("scrutiny of grades", 3)
    assert result.found and all(p.origin == "official" for p in result.passages)
