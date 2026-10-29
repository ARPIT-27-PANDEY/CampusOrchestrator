"""Repeatable, idempotent ingestion of academic PDFs into Qdrant.

* A document's version is the sha256 of its bytes. Unchanged files are skipped,
  so restarting the server never inserts duplicate chunks.
* A changed file has its old chunks deleted before the new ones are inserted.
* Files removed from the directory are pruned from the index.
* Point ids are uuid5(chunk_id), so even a forced re-run overwrites in place.
* Files listed in the source manifest (``data/sources/iitr_sources.yaml``) are official
  documents: they get the official title, URL, issue date, status and applicability on every
  chunk and use the general ``chunk_official`` chunker. Other files use the demo chunker.
* A PDF with too little extractable text (scanned/image-only) is NOT indexed; it is reported
  under ``needs_ocr`` so coverage is never overstated.

CLI:  python -m academics_mcp.ingest [--dir PATH] [--force] [--dry-run] [--json]
"""

from __future__ import annotations

import argparse
import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .chunking import chunk_document, chunk_official
from .embeddings import Embedder
from .index import HandbookIndex
from .pdf import PdfExtractionError, extract_pdf, file_sha256
from .sources import MIN_TEXT_CHARS_PER_PAGE, Manifest

log = logging.getLogger("academics_mcp.ingest")


@dataclass
class IngestReport:
    added: list[str] = field(default_factory=list)
    replaced: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    empty: list[str] = field(default_factory=list)
    needs_ocr: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    chunks_written: int = 0
    directory: str = ""
    collection: str = ""
    embedding_model: str = ""
    dry_run: bool = False


def ingest_directory(
    directory: Path,
    index: HandbookIndex,
    embedder: Embedder,
    *,
    force: bool = False,
    prune: bool = True,
    manifest: Manifest | None = None,
    dry_run: bool = False,
) -> IngestReport:
    report = IngestReport(
        directory=str(directory), collection=index.collection, embedding_model=embedder.name, dry_run=dry_run
    )
    if not dry_run:
        index.ensure_collection()
    pdfs = sorted(directory.glob("*.pdf")) if directory.exists() else []
    if not directory.exists():
        log.warning("Handbook directory %s does not exist; index will be empty", directory)
    official = manifest.by_filename() if manifest else {}

    for path in pdfs:
        try:
            version = file_sha256(path)[:12]
            existing = (
                index.versions_for_source(path.name) if index.client.collection_exists(index.collection) else set()
            )
            if not force and existing == {(version, embedder.name)}:
                report.unchanged.append(path.name)
                continue
            doc = extract_pdf(path)
            source = official.get(path.name)
            text_chars = sum(len(p.text.strip()) for p in doc.pages)
            if doc.pages and text_chars / len(doc.pages) < MIN_TEXT_CHARS_PER_PAGE:
                report.needs_ocr.append(path.name)  # scanned PDF: needs OCR or manual text
                if not dry_run:
                    index.delete_source(path.name)
                continue
            if source:
                doc = type(doc)(path=doc.path, title=source.title, content_hash=doc.content_hash, pages=doc.pages)
                tables = source.doc_type == "calendar"  # row tables: no heading detection, smaller chunks
                chunks = chunk_official(doc, max_chars=450 if tables else 900, headings=not tables)
            else:
                chunks = chunk_document(doc)
            if not chunks:
                report.empty.append(path.name)
                if not dry_run:
                    index.delete_source(path.name)
                continue
            if dry_run:
                (report.replaced if existing else report.added).append(path.name)
                report.chunks_written += len(chunks)
                continue
            index.delete_source(path.name)
            vectors = embedder.embed_documents([f"{c.section}. {c.text}" for c in chunks])
            index.upsert_chunks(chunks, vectors, page_count=len(doc.pages), extra=source.payload() if source else None)
            report.chunks_written += len(chunks)
            (report.replaced if existing else report.added).append(path.name)
        except PdfExtractionError as exc:
            report.errors[path.name] = str(exc)
            log.error("Failed to ingest %s: %s", path.name, exc)

    if prune and not dry_run:
        present = {p.name for p in pdfs}
        for indexed in index.documents():
            if indexed.source_filename not in present:
                index.delete_source(indexed.source_filename)
                report.removed.append(indexed.source_filename)
    log.info(
        "Ingestion complete: added=%s replaced=%s unchanged=%s removed=%s empty=%s needs_ocr=%s errors=%s chunks=%d",
        report.added, report.replaced, report.unchanged, report.removed, report.empty, report.needs_ocr,
        list(report.errors), report.chunks_written,
    )  # fmt: skip
    return report


def main() -> None:  # pragma: no cover - thin CLI wrapper
    from .config import AcademicsSettings
    from .service import build_index_and_embedder, load_manifest_for

    parser = argparse.ArgumentParser(description="Ingest academic PDFs into Qdrant")
    parser.add_argument("--dir", type=Path, default=None)
    parser.add_argument("--force", action="store_true", help="Re-embed even unchanged documents")
    parser.add_argument("--dry-run", action="store_true", help="Extract and chunk, but do not write the index")
    parser.add_argument("--json", action="store_true", help="Print the report as JSON")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    settings = AcademicsSettings.from_env()
    index, embedder = build_index_and_embedder(settings)
    directory = args.dir or settings.handbook_dir
    report = ingest_directory(
        directory, index, embedder, force=args.force, manifest=load_manifest_for(settings), dry_run=args.dry_run
    )
    print(json.dumps(asdict(report), indent=2) if args.json else report)


if __name__ == "__main__":  # pragma: no cover
    main()
