"""Execution-trace storage with retention and privacy controls.

Backends
* ``memory`` (default): bounded, lost on restart.
* ``sqlite``: single-file store that survives restarts. It is meant for ONE backend instance; several
  workers or instances need a shared database instead (documented in docs/security.md).

Privacy (applied to every stored copy, in both backends and the optional JSONL export)
* Secrets and personal data (API keys, bearer tokens, e-mail addresses, phone and ID-like numbers) are
  always masked when ``redact`` is on.
* ``keep_query=False`` replaces the user's question with a placeholder and a short hash.
* ``keep_payloads=False`` drops tool argument values, raw tool-result previews and shortens document
  excerpts, so the trace still shows *what* happened without storing the content.
* Traces older than ``retention_s`` and beyond ``capacity`` are deleted.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import threading
import time
from collections import OrderedDict
from pathlib import Path
from typing import Any

from .models import AgentTrace

log = logging.getLogger("campusos.traces")

_REDACTIONS = [
    (re.compile(r"\b(gsk|sk|pk|rk)_[A-Za-z0-9_\-]{16,}\b"), "[api-key]"),
    (re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{12,}", re.I), "Bearer [token]"),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\b"), "[jwt]"),
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "[email]"),
    (re.compile(r"\b\d{4}[ \-]?\d{4}[ \-]?\d{4}\b"), "[id-number]"),
    (re.compile(r"(?<!\d)(?:\+?91[ \-]?)?[6-9]\d{4}[ \-]?\d{5}(?!\d)"), "[phone]"),
]
QUERY_PLACEHOLDER = "[query not retained]"


def redact(text: str) -> str:
    for pattern, repl in _REDACTIONS:
        text = pattern.sub(repl, text)
    return text


def _walk(node: Any, fn: Any) -> Any:
    if isinstance(node, str):
        return fn(node)
    if isinstance(node, list):
        return [_walk(v, fn) for v in node]
    if isinstance(node, dict):
        return {k: _walk(v, fn) for k, v in node.items()}
    return node


class TracePrivacy:
    def __init__(self, keep_query: bool = True, keep_payloads: bool = True, redact_text: bool = True) -> None:
        self.keep_query = keep_query
        self.keep_payloads = keep_payloads
        self.redact = redact_text

    def apply(self, trace: AgentTrace) -> dict[str, Any]:
        data: dict[str, Any] = trace.model_dump(mode="json")
        if not self.keep_query:
            digest = hashlib.sha256(trace.query.encode()).hexdigest()[:10]
            data["query"] = f"{QUERY_PLACEHOLDER} #{digest}"
            if data.get("result"):
                data["result"]["query"] = data["query"]
        if not self.keep_payloads:
            for step in data.get("steps", []):
                detail = step.get("detail", {})
                if isinstance(detail.get("arguments"), dict):
                    detail["arguments"] = {k: "[omitted]" for k in detail["arguments"]}
                detail.pop("result_preview", None)
            result = data.get("result") or {}
            for call in result.get("tool_calls", []):
                if isinstance(call.get("arguments"), dict):
                    call["arguments"] = {k: "[omitted]" for k in call["arguments"]}
            for cite in result.get("citations", []):
                cite["excerpt"] = str(cite.get("excerpt", ""))[:160]
        if self.redact:
            data = _walk(data, redact)
        return data


class TraceStore:
    def __init__(
        self,
        capacity: int = 200,
        log_path: Path | None = None,
        *,
        backend: str = "memory",
        db_path: Path | None = None,
        retention_s: float | None = None,
        privacy: TracePrivacy | None = None,
    ) -> None:
        self._capacity = capacity
        self._log_path = log_path
        self._retention = retention_s
        self.privacy = privacy or TracePrivacy()
        self.backend = backend
        self._items: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()
        self._lock = threading.Lock()
        self._db: sqlite3.Connection | None = None
        if backend == "sqlite":
            if db_path is None:
                raise ValueError("TRACE_BACKEND=sqlite requires TRACE_DB_PATH")
            db_path.parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(str(db_path), check_same_thread=False)
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS traces (trace_id TEXT PRIMARY KEY, created_at REAL NOT NULL, "
                "status TEXT, data TEXT NOT NULL)"
            )
            self._db.execute("CREATE INDEX IF NOT EXISTS traces_created ON traces(created_at)")
            self._db.commit()
        elif backend != "memory":
            raise ValueError(f"Unknown trace backend {backend!r} (memory or sqlite).")

    # ------------------------------------------------------------------ writes
    def _store(self, trace: AgentTrace) -> None:
        data = self.privacy.apply(trace)
        created = trace.created_at.timestamp()
        with self._lock:
            if self._db is not None:
                self._db.execute(
                    "INSERT INTO traces(trace_id, created_at, status, data) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(trace_id) DO UPDATE SET status=excluded.status, data=excluded.data",
                    (trace.trace_id, created, trace.status, json.dumps(data, default=str)),
                )
                self._db.commit()
            else:
                self._items[trace.trace_id] = (created, data)
                self._items.move_to_end(trace.trace_id)
        self.cleanup()

    def put(self, trace: AgentTrace) -> None:
        self._store(trace)

    def finish(self, trace: AgentTrace) -> None:
        self._store(trace)
        if self._log_path:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with self._log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(self.privacy.apply(trace), default=str) + "\n")

    def cleanup(self, now: float | None = None) -> int:
        """Delete expired traces and enforce the capacity. Returns the number removed."""
        cutoff = (now or time.time()) - self._retention if self._retention else None
        removed = 0
        with self._lock:
            if self._db is not None:
                if cutoff is not None:
                    removed += self._db.execute("DELETE FROM traces WHERE created_at < ?", (cutoff,)).rowcount
                removed += self._db.execute(
                    "DELETE FROM traces WHERE trace_id NOT IN "
                    "(SELECT trace_id FROM traces ORDER BY created_at DESC LIMIT ?)",
                    (self._capacity,),
                ).rowcount
                self._db.commit()
            else:
                if cutoff is not None:
                    for tid in [t for t, (c, _) in self._items.items() if c < cutoff]:
                        del self._items[tid]
                        removed += 1
                while len(self._items) > self._capacity:
                    self._items.popitem(last=False)
                    removed += 1
        return removed

    # ------------------------------------------------------------------ reads
    @staticmethod
    def _load(trace_id: str, raw: str | dict[str, Any]) -> AgentTrace | None:
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
            return AgentTrace.model_validate(data)
        except (ValueError, TypeError) as exc:
            log.warning("Skipping unreadable stored trace %s: %s", trace_id, type(exc).__name__)
            return None

    def get(self, trace_id: str) -> AgentTrace | None:
        self.cleanup()
        with self._lock:
            if self._db is not None:
                row = self._db.execute("SELECT data FROM traces WHERE trace_id = ?", (trace_id,)).fetchone()
                raw: str | dict[str, Any] | None = row[0] if row else None
            else:
                item = self._items.get(trace_id)
                raw = item[1] if item else None
        return self._load(trace_id, raw) if raw is not None else None

    def recent(self, limit: int = 50) -> list[AgentTrace]:
        self.cleanup()
        items: list[tuple[str, Any]]  # stored JSON text (sqlite) or the already-sanitised dict (memory)
        with self._lock:
            if self._db is not None:
                rows = self._db.execute(
                    "SELECT trace_id, data FROM traces ORDER BY created_at DESC LIMIT ?", (limit,)
                ).fetchall()
                items = [(r[0], r[1]) for r in rows]
            else:
                items = [(tid, raw) for tid, (_, raw) in reversed(self._items.items())][:limit]
        loaded = [self._load(tid, raw) for tid, raw in items]
        return [t for t in loaded if t is not None]

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None
