"""Curated official-source manifest and a safe, allowlisted downloader.

* ``iitr_sources.yaml`` holds hand-curated metadata (title, authority, dates, applicability,
  supersession). ``iitr_sources.lock.json`` holds machine-written fetch results (sha256,
  retrieval time, size, pages, extractable text, status, error).
* Only manifest URLs on ``allowed_hosts`` are fetched. Redirects are followed manually and
  every hop is re-checked against the allowlist. Responses are size-capped, must start with
  ``%PDF``, and are written atomically: a failed or empty download never replaces a good file.
* Scanned/image-only PDFs are detected (too little extractable text) and reported as needing
  OCR or manual text instead of being silently indexed as "covered".

CLI (from services/academics_mcp):
    python -m academics_mcp.sources fetch [--only ID ...] [--dry-run]
    python -m academics_mcp.sources check          # re-hash local files, report changed/missing
    python -m academics_mcp.sources report         # print the lock file as a table
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
import yaml

DATA_DIR = Path(__file__).resolve().parents[1] / "data"
DEFAULT_MANIFEST = DATA_DIR / "sources" / "iitr_sources.yaml"
DEFAULT_DOC_DIR = DATA_DIR / "iitr"
USER_AGENT = "CampusOrchestrator/0.2 (+https://github.com/ARPIT-27-PANDEY/CampusOrchestrator)"
MAX_BYTES = 40 * 1024 * 1024
MIN_TEXT_CHARS_PER_PAGE = 40  # below this on average, the PDF is treated as scanned/image-only


class SourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceDoc:
    id: str
    title: str
    authority: str
    doc_type: str
    url: str
    listed_on: str | None
    issued: str | None
    reference: str | None
    effective: str | None
    academic_year: str | None
    applies_to: list[str]
    status: str
    supersedes: list[str]
    superseded_by: list[str]
    usage_note: str
    note: str | None = None

    @property
    def filename(self) -> str:
        return f"{self.id}.pdf"

    def payload(self) -> dict[str, Any]:
        """Metadata attached to every indexed chunk of this document."""
        return {
            "source_id": self.id,
            "official_title": self.title,
            "authority": self.authority,
            "doc_type": self.doc_type,
            "source_url": self.url,
            "issued": self.issued,
            "reference": self.reference,
            "effective": self.effective,
            "academic_year": self.academic_year,
            "applies_to": self.applies_to,
            "doc_status": self.status,
            "supersedes": self.supersedes,
            "superseded_by": self.superseded_by,
        }


@dataclass
class Manifest:
    path: Path
    allowed_hosts: set[str]
    documents: list[SourceDoc]
    lock: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def lock_path(self) -> Path:
        return self.path.with_suffix(".lock.json")

    def by_filename(self) -> dict[str, SourceDoc]:
        return {d.filename: d for d in self.documents}

    def save_lock(self) -> None:
        self.lock_path.write_text(json.dumps(self.lock, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_manifest(path: Path = DEFAULT_MANIFEST) -> Manifest:
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    hosts = {str(h).lower() for h in raw.get("allowed_hosts", [])}
    authority = str(raw.get("authority_default", ""))
    usage = str(raw.get("usage_note_default", "")).strip()
    docs: list[SourceDoc] = []
    seen: set[str] = set()
    for d in raw.get("documents", []):
        if d["id"] in seen:
            raise SourceError(f"Duplicate source id {d['id']!r} in {path.name}")
        seen.add(d["id"])
        _check_url(d["url"], hosts)

        def _date(key: str, d: dict[str, Any] = d) -> str | None:
            v = d.get(key)
            return None if v is None else str(v)

        docs.append(
            SourceDoc(
                id=d["id"],
                title=d["title"],
                authority=d.get("authority", authority),
                doc_type=d["doc_type"],
                url=d["url"],
                listed_on=d.get("listed_on"),
                issued=_date("issued"),
                reference=d.get("reference"),
                effective=_date("effective"),
                academic_year=_date("academic_year"),
                applies_to=[str(x) for x in d.get("applies_to", ["all"])],
                status=d.get("status", "uncertain"),
                supersedes=list(d.get("supersedes", [])),
                superseded_by=list(d.get("superseded_by", [])),
                usage_note=d.get("usage_note", usage),
                note=d.get("note"),
            )
        )
    manifest = Manifest(path=path, allowed_hosts=hosts, documents=docs)
    if manifest.lock_path.exists():
        manifest.lock = json.loads(manifest.lock_path.read_text(encoding="utf-8"))
    return manifest


def _check_url(url: str, allowed_hosts: set[str]) -> None:
    parsed = urlparse(url)
    if parsed.scheme != "https" or (parsed.hostname or "").lower() not in allowed_hosts:
        raise SourceError(f"URL not allowed (https + {sorted(allowed_hosts)} only): {url}")
    if parsed.username or parsed.password:
        raise SourceError("Credentials in source URLs are not allowed.")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def download(url: str, allowed_hosts: set[str], client: httpx.Client, max_bytes: int = MAX_BYTES) -> bytes:
    """GET with manual, allowlist-checked redirects, a size cap and a PDF signature check."""
    current = url
    for _ in range(5):
        _check_url(current, allowed_hosts)
        with client.stream("GET", current) as resp:
            if resp.status_code in (301, 302, 303, 307, 308):
                current = urljoin(current, resp.headers.get("location", ""))
                continue
            if resp.status_code != 200:
                raise SourceError(f"HTTP {resp.status_code}")
            declared = int(resp.headers.get("content-length") or 0)
            if declared > max_bytes:
                raise SourceError(f"File too large ({declared} bytes > {max_bytes})")
            chunks: list[bytes] = []
            total = 0
            for chunk in resp.iter_bytes():
                total += len(chunk)
                if total > max_bytes:
                    raise SourceError(f"File too large (> {max_bytes} bytes)")
                chunks.append(chunk)
            data = b"".join(chunks)
            if not data.startswith(b"%PDF"):
                raise SourceError("Response is not a PDF (missing %PDF signature)")
            return data
    raise SourceError("Too many redirects")


def inspect_pdf(path: Path) -> dict[str, Any]:
    """Page count and extractable-text size; flags likely scanned (image-only) PDFs."""
    from .pdf import extract_pdf

    doc = extract_pdf(path)
    chars = sum(len(p.text.strip()) for p in doc.pages)
    pages = len(doc.pages)
    scanned = pages > 0 and chars / pages < MIN_TEXT_CHARS_PER_PAGE
    return {"pages": pages, "text_chars": chars, "needs_ocr": scanned}


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".part")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


@dataclass
class FetchReport:
    added: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    failed: dict[str, str] = field(default_factory=dict)
    needs_ocr: list[str] = field(default_factory=list)
    dry_run: bool = False


def fetch_all(
    manifest: Manifest,
    doc_dir: Path = DEFAULT_DOC_DIR,
    *,
    only: set[str] | None = None,
    dry_run: bool = False,
    client: httpx.Client | None = None,
) -> FetchReport:
    report = FetchReport(dry_run=dry_run)
    own = client is None
    http = client or httpx.Client(timeout=60.0, headers={"User-Agent": USER_AGENT}, follow_redirects=False)
    try:
        for doc in manifest.documents:
            if only and doc.id not in only:
                continue
            target = doc_dir / doc.filename
            entry = manifest.lock.setdefault(doc.id, {})
            try:
                data = download(doc.url, manifest.allowed_hosts, http)
            except (SourceError, httpx.HTTPError) as exc:
                report.failed[doc.id] = f"{type(exc).__name__}: {exc}"
                entry.update(last_attempt_at=_now(), status="fetch_failed", error=report.failed[doc.id])
                continue  # the previous good file (if any) is kept
            digest = sha256_bytes(data)
            old = sha256_bytes(target.read_bytes()) if target.exists() else None
            bucket = report.unchanged if old == digest else report.updated if old else report.added
            bucket.append(doc.id)
            if dry_run:
                continue
            if old != digest:
                _atomic_write(target, data)
            info = inspect_pdf(target)
            if info["needs_ocr"]:
                report.needs_ocr.append(doc.id)
            entry.update(
                file=f"{doc_dir.name}/{doc.filename}", sha256=digest, bytes=len(data), retrieved_at=_now(),
                last_attempt_at=_now(), status="needs_ocr" if info["needs_ocr"] else "ok", error=None,
                pages=info["pages"], text_chars=info["text_chars"], url=doc.url,
            )  # fmt: skip
    finally:
        if own:
            http.close()
    if not dry_run:
        manifest.save_lock()
    return report


def check_local(manifest: Manifest, doc_dir: Path = DEFAULT_DOC_DIR) -> dict[str, str]:
    """Compare local files with the lock: ok | changed | missing | unfetched."""
    out: dict[str, str] = {}
    for doc in manifest.documents:
        path = doc_dir / doc.filename
        locked = manifest.lock.get(doc.id, {}).get("sha256")
        if not path.exists():
            out[doc.id] = "missing" if locked else "unfetched"
        elif locked and sha256_bytes(path.read_bytes()) != locked:
            out[doc.id] = "changed"
        else:
            out[doc.id] = "ok" if locked else "unfetched"
    return out


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - thin CLI
    parser = argparse.ArgumentParser(description="Manage the curated IIT Roorkee source documents")
    sub = parser.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch", help="Download manifest documents (allowlisted hosts only)")
    f.add_argument("--only", nargs="*", default=None, help="Document ids to fetch")
    f.add_argument("--dry-run", action="store_true", help="Download and compare, but write nothing")
    sub.add_parser("check", help="Report local files that changed or are missing")
    sub.add_parser("report", help="Show the lock file")
    for p in (f,):
        p.add_argument("--dir", type=Path, default=DEFAULT_DOC_DIR)
    args = parser.parse_args(argv)
    manifest = load_manifest()
    if args.cmd == "fetch":
        rep = fetch_all(manifest, args.dir, only=set(args.only) if args.only else None, dry_run=args.dry_run)
        print(json.dumps(rep.__dict__, indent=2))
        return 1 if rep.failed else 0
    if args.cmd == "check":
        status = check_local(manifest)
        for k, v in status.items():
            print(f"{v:<10} {k}")
        return 0 if all(v == "ok" for v in status.values()) else 1
    for doc in manifest.documents:
        e = manifest.lock.get(doc.id, {})
        print(f"{e.get('status', 'unfetched'):<12} {e.get('pages', '-'):>4}p {e.get('bytes', 0):>9}B  {doc.id}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
