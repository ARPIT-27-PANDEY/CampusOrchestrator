"""Official-source manifest, safe downloader, scanned-PDF handling, supersession and hybrid fusion."""

from __future__ import annotations

from pathlib import Path

import httpx
import pymupdf
import pytest
import yaml

from academics_mcp.config import AcademicsSettings
from academics_mcp.hybrid import LexicalIndex, rrf_fuse
from academics_mcp.index import SearchHit
from academics_mcp.ingest import ingest_directory
from academics_mcp.server import build_service
from academics_mcp.service import collection_name
from academics_mcp.sources import SourceError, check_local, download, fetch_all, load_manifest


def _pdf(path: Path, pages: list[str]) -> bytes:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 550, 800), text, fontsize=10)
    doc.save(path)
    return path.read_bytes()


def _scanned(path: Path) -> bytes:
    doc = pymupdf.open()
    page = doc.new_page()
    page.draw_rect(pymupdf.Rect(50, 50, 300, 300), fill=(0.2, 0.2, 0.2))  # image-like, no text layer
    doc.save(path)
    return path.read_bytes()


OLD = "Subject: Guidelines on unfair means\n1. A student caught with prohibited items in an examination gets a warning."
NEW = (
    "Subject: Revision of unfair means guidelines\n"
    "1. A student caught carrying prohibited items repeatedly in an examination gets a course backlog."
)
PHD = "Subject: Ph.D. thesis submission\n1. A Ph.D. scholar must submit the thesis within six years of registration."


@pytest.fixture
def corpus(tmp_path: Path) -> tuple[Path, Path]:
    docs = tmp_path / "iitr"
    docs.mkdir()
    _pdf(docs / "ufm-2025.pdf", [OLD])
    _pdf(docs / "ufm-2026.pdf", [NEW])
    _pdf(docs / "phd-2026.pdf", [PHD])
    _scanned(docs / "scanned-2016.pdf")
    manifest = {
        "version": 1,
        "authority_default": "Academic Affairs Office, IIT Roorkee",
        "allowed_hosts": ["iitr.ac.in"],
        "documents": [
            {"id": "ufm-2025", "title": "UFM Guidelines 2025", "doc_type": "notification", "issued": "2025-02-04",
             "url": "https://iitr.ac.in/x/ufm-2025.pdf", "status": "superseded", "superseded_by": ["ufm-2026"]},
            {"id": "ufm-2026", "title": "UFM Revision 2026", "doc_type": "notification", "issued": "2026-04-15",
             "url": "https://iitr.ac.in/x/ufm-2026.pdf", "status": "current", "supersedes": ["ufm-2025"]},
            {"id": "phd-2026", "title": "PhD Regulations 2026", "doc_type": "regulation", "applies_to": ["phd"],
             "url": "https://iitr.ac.in/x/phd-2026.pdf", "status": "current"},
            {"id": "scanned-2016", "title": "Old Scanned Ordinance", "doc_type": "regulation",
             "url": "https://iitr.ac.in/x/scanned-2016.pdf", "status": "superseded"},
        ],
    }  # fmt: skip
    path = tmp_path / "sources.yaml"
    path.write_text(yaml.safe_dump(manifest), encoding="utf-8")
    return docs, path


def _service(corpus: tuple[Path, Path], **kw: object) -> object:
    docs, manifest = corpus
    return build_service(AcademicsSettings(handbook_dir=docs, manifest_path=manifest, qdrant_path=":memory:", **kw))  # type: ignore[arg-type]


def test_manifest_rejects_non_allowlisted_and_non_https_urls(tmp_path: Path) -> None:
    for url in ("https://evil.example/x.pdf", "http://iitr.ac.in/x.pdf", "https://user:pw@iitr.ac.in/x.pdf"):
        bad = {"allowed_hosts": ["iitr.ac.in"], "documents": [{"id": "a", "title": "A", "doc_type": "x", "url": url}]}
        path = tmp_path / "m.yaml"
        path.write_text(yaml.safe_dump(bad), encoding="utf-8")
        with pytest.raises(SourceError):
            load_manifest(path)


def test_download_refuses_redirect_to_another_host() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://evil.example/payload.pdf"})

    with httpx.Client(transport=httpx.MockTransport(handle)) as client, pytest.raises(SourceError, match="not allowed"):
        download("https://iitr.ac.in/a.pdf", {"iitr.ac.in"}, client)


def test_download_rejects_non_pdf_and_oversized() -> None:
    html = httpx.MockTransport(lambda r: httpx.Response(200, content=b"<html>login</html>"))
    with httpx.Client(transport=html) as client, pytest.raises(SourceError, match="not a PDF"):
        download("https://iitr.ac.in/a.pdf", {"iitr.ac.in"}, client)
    big = httpx.MockTransport(lambda r: httpx.Response(200, content=b"%PDF" + b"0" * 2000))
    with httpx.Client(transport=big) as client, pytest.raises(SourceError, match="too large"):
        download("https://iitr.ac.in/a.pdf", {"iitr.ac.in"}, client, max_bytes=1000)


def test_failed_download_keeps_existing_file_and_records_error(corpus: tuple[Path, Path]) -> None:
    docs, manifest_path = corpus
    manifest = load_manifest(manifest_path)
    before = (docs / "ufm-2026.pdf").read_bytes()
    failing = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    report = fetch_all(manifest, docs, only={"ufm-2026"}, client=failing)
    assert "ufm-2026" in report.failed
    assert (docs / "ufm-2026.pdf").read_bytes() == before  # never replaced by a failed download
    assert manifest.lock["ufm-2026"]["status"] == "fetch_failed"


def test_fetch_records_hash_and_detects_changes(corpus: tuple[Path, Path], tmp_path: Path) -> None:
    docs, manifest_path = corpus
    manifest = load_manifest(manifest_path)
    payload = (docs / "ufm-2026.pdf").read_bytes()
    out = tmp_path / "fresh"
    ok = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=payload)))
    report = fetch_all(manifest, out, only={"ufm-2026"}, client=ok)
    assert report.added == ["ufm-2026"] and manifest.lock["ufm-2026"]["status"] == "ok"
    assert check_local(manifest, out)["ufm-2026"] == "ok"
    (out / "ufm-2026.pdf").write_bytes(payload + b"\n%changed")
    assert check_local(manifest, out)["ufm-2026"] == "changed"


def test_scanned_pdf_is_reported_not_indexed(corpus: tuple[Path, Path]) -> None:
    svc = _service(corpus)
    info = svc.source_info()  # type: ignore[attr-defined]
    assert "scanned-2016.pdf" not in {d.source_filename for d in info.documents}
    assert any("scanned-2016.pdf" in n and "OCR" in n for n in info.not_indexed)
    assert info.mode == "imported"  # official documents only, no demo files


def test_passages_carry_official_metadata_and_current_doc_ranks_first(corpus: tuple[Path, Path]) -> None:
    svc = _service(corpus)
    result = svc.search("student caught with prohibited items in examination", 4)  # type: ignore[attr-defined]
    titles = [p.document_title for p in result.passages]
    assert titles[0] == "UFM Revision 2026"  # current document preferred over the superseded one
    old = next(p for p in result.passages if p.document_title == "UFM Guidelines 2025")
    assert old.doc_status == "superseded" and old.superseded_by == ["UFM Revision 2026"]
    assert old.source_url == "https://iitr.ac.in/x/ufm-2025.pdf" and old.origin == "official"
    assert any("superseded by UFM Revision 2026" in n for n in result.applicability_notes)


def test_programme_specific_document_gets_an_applicability_note(corpus: tuple[Path, Path]) -> None:
    result = _service(corpus).search("thesis submission within six years", 3)  # type: ignore[attr-defined]
    assert result.found
    assert any("applies to: phd" in n for n in result.applicability_notes)


def test_reingest_with_manifest_is_idempotent(corpus: tuple[Path, Path]) -> None:
    svc = _service(corpus)
    docs, manifest_path = corpus
    report = ingest_directory(docs, svc.index, svc.embedder, manifest=load_manifest(manifest_path))  # type: ignore[attr-defined]
    assert sorted(report.unchanged) == ["phd-2026.pdf", "ufm-2025.pdf", "ufm-2026.pdf"]
    assert report.needs_ocr == ["scanned-2016.pdf"] and report.chunks_written == 0


def test_dry_run_writes_nothing(corpus: tuple[Path, Path]) -> None:
    svc = _service(corpus)
    docs, manifest_path = corpus
    _pdf(docs / "new-doc.pdf", ["Subject: Something new\n1. A brand new rule about libraries and reading rooms."])
    before = {d.source_filename for d in svc.index.documents()}  # type: ignore[attr-defined]
    report = ingest_directory(docs, svc.index, svc.embedder, manifest=load_manifest(manifest_path), dry_run=True)  # type: ignore[attr-defined]
    assert report.added == ["new-doc.pdf"] and report.dry_run
    assert {d.source_filename for d in svc.index.documents()} == before  # type: ignore[attr-defined]


def test_collections_are_separated_per_embedding_model() -> None:
    assert collection_name("campus", "hashing-v1-512") == "campus__hashing_v1_512"
    assert collection_name("campus", "fastembed:BAAI/bge-small-en-v1.5") == "campus__fastembed_baai_bge_small_en_v1_5"


def test_rrf_fuses_by_chunk_and_rewards_agreement() -> None:
    a = [SearchHit(0.9, {"chunk_id": "x"}), SearchHit(0.8, {"chunk_id": "y"})]
    b = [SearchHit(5.0, {"chunk_id": "y"}), SearchHit(4.0, {"chunk_id": "z"})]
    fused = rrf_fuse(a, b)
    assert next(h.payload["chunk_id"] for h in fused) == "y"  # ranked by both lists
    assert {h.payload["chunk_id"] for h in fused} == {"x", "y", "z"}


def test_bm25_prefers_rare_matching_terms() -> None:
    idx = LexicalIndex.from_payloads(
        [
            {"chunk_id": "1", "section": "Fees", "text": "students pay fees each semester"},
            {"chunk_id": "2", "section": "Attendance", "text": "attendance is recorded for every lecture"},
        ]
    )
    assert [h.payload["chunk_id"] for h in idx.search("attendance lecture", 2)] == ["2"]


def test_hybrid_mode_returns_results(corpus: tuple[Path, Path]) -> None:
    svc = _service(corpus, retrieval_mode="hybrid")
    result = svc.search("prohibited items repeatedly examination backlog", 2)  # type: ignore[attr-defined]
    assert result.found and result.source.retrieval == "hybrid"
    assert result.passages[0].document_title == "UFM Revision 2026"
