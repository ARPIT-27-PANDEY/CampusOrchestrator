"""Repeatable, idempotent ingestion of academic PDFs into Qdrant.

* A document's version is the sha256 of its bytes. Unchanged files are skipped,
  so restarting the server never inserts duplicate chunks.
* A changed file has its old chunks deleted before the new ones are inserted.
* Files removed from the directory are pruned from the index.
* Point ids are uuid5(chunk_id), so even a forced re-run overwrites in place.

CLI:  python -m academics_mcp.ingest [--dir PATH] [--force]
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass, field
from pathlib import Path

from .chunking import chunk_document
from .embeddings import Embedder
from .index import HandbookIndex
from .pdf import PdfExtractionError, extract_pdf, file_sha256

log = logging.getLogger("academics_mcp.ingest")


@dataclass
class IngestReport:
    added: list[str] = field(default_factory=list)
    replaced: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    empty: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)
    chunks_written: int = 0


def ingest_directory(
    directory: Path, index: HandbookIndex, embedder: Embedder, *, force: bool = False, prune: bool = True
) -> IngestReport:
    report = IngestReport()
    index.ensure_collection()
    pdfs = sorted(directory.glob("*.pdf")) if directory.exists() else []
    if not directory.exists():
        log.warning("Handbook directory %s does not exist; index will be empty", directory)

    for path in pdfs:
        try:
            version = file_sha256(path)[:12]
            existing = index.versions_for_source(path.name)
            if not force and existing == {(version, embedder.name)}:
                report.unchanged.append(path.name)
                continue
            doc = extract_pdf(path)
            chunks = chunk_document(doc)
            index.delete_source(path.name)
            if not chunks:
                report.empty.append(path.name)  # e.g. scanned PDF without a text layer
                continue
            vectors = embedder.embed_documents([f"{c.section}. {c.text}" for c in chunks])
            index.upsert_chunks(chunks, vectors, page_count=len(doc.pages))
            report.chunks_written += len(chunks)
            (report.replaced if existing else report.added).append(path.name)
        except PdfExtractionError as exc:
            report.errors[path.name] = str(exc)
            log.error("Failed to ingest %s: %s", path.name, exc)

    if prune:
        present = {p.name for p in pdfs}
        for indexed in index.documents():
            if indexed.source_filename not in present:
                index.delete_source(indexed.source_filename)
                report.removed.append(indexed.source_filename)
    log.info(
        "Ingestion complete: added=%s replaced=%s unchanged=%s removed=%s empty=%s errors=%s chunks=%d",
        report.added, report.replaced, report.unchanged, report.removed, report.empty, list(report.errors),
        report.chunks_written,
    )  # fmt: skip
    return report


def main() -> None:  # pragma: no cover - thin CLI wrapper
    from .config import AcademicsSettings
    from .service import build_index_and_embedder

    parser = argparse.ArgumentParser(description="Ingest academic PDFs into Qdrant")
    parser.add_argument("--dir", type=Path, default=None)
    parser.add_argument("--force", action="store_true", help="Re-embed even unchanged documents")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    settings = AcademicsSettings.from_env()
    index, embedder = build_index_and_embedder(settings)
    report = ingest_directory(args.dir or settings.handbook_dir, index, embedder, force=args.force)
    print(report)


if __name__ == "__main__":  # pragma: no cover
    main()
