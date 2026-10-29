"""Trace persistence, retention, bounded size, redaction and malformed data."""

from __future__ import annotations

import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from app.agent.models import AgentResult, AgentTrace, Citation, ToolCallSummary, TraceStep
from app.agent.trace_store import QUERY_PLACEHOLDER, TracePrivacy, TraceStore, redact


def _trace(tid: str, query: str = "my email is a.student@iitr.ac.in", age_s: float = 0) -> AgentTrace:
    created = datetime.now(UTC) - timedelta(seconds=age_s)
    call = ToolCallSummary(call_id="c", tool="library__search_books", server_id="library",
                           arguments={"query": "notes for roll 21114001"}, status="success", duration_ms=1, attempts=1)  # fmt: skip
    result = AgentResult(
        trace_id=tid, query=query, answer="ok", status="ok", provider="mock", model="m", tool_calls=[call],
        citations=[Citation(number=1, citation_id="x", document_title="D", source_filename="d.pdf",
                            document_version="v", page=1, excerpt="A" * 600)],
    )  # fmt: skip
    step = TraceStep(
        kind="tool", started_at=created, detail={"arguments": {"query": "secret"}, "result_preview": "{...}"}
    )
    return AgentTrace(trace_id=tid, created_at=created, query=query, provider="mock", model="m", status="ok",
                      steps=[step], result=result)  # fmt: skip


def test_redaction_masks_secrets_and_personal_data() -> None:
    text = "key gsk_abcdefghijklmnopqrstuv mail a.b@iitr.ac.in phone +91 98765 43210 Bearer abc.def.ghi123456"
    out = redact(text)
    assert "gsk_" not in out and "@iitr" not in out and "98765" not in out and "abc.def" not in out


def test_privacy_drops_query_and_payloads_when_configured() -> None:
    store = TraceStore(privacy=TracePrivacy(keep_query=False, keep_payloads=False))
    store.finish(_trace("t1"))
    got = store.get("t1")
    assert got is not None and got.query.startswith(QUERY_PLACEHOLDER)
    assert got.steps[0].detail["arguments"] == {"query": "[omitted]"} and "result_preview" not in got.steps[0].detail
    assert got.result is not None and got.result.tool_calls[0].arguments == {"query": "[omitted]"}
    assert len(got.result.citations[0].excerpt) <= 160


def test_redaction_applies_even_when_query_text_is_kept() -> None:
    store = TraceStore(privacy=TracePrivacy(keep_query=True, keep_payloads=True))
    store.finish(_trace("t1"))
    got = store.get("t1")
    assert got is not None and "[email]" in got.query and "iitr.ac.in" not in got.query


def test_memory_store_is_bounded_and_expires() -> None:
    store = TraceStore(capacity=3, retention_s=60)
    for i in range(5):
        store.finish(_trace(f"t{i}"))
    assert [t.trace_id for t in store.recent(10)] == ["t4", "t3", "t2"]
    store.finish(_trace("old", age_s=120))
    assert store.get("old") is None  # already past retention


def test_sqlite_store_survives_restart_and_enforces_retention(tmp_path: Path) -> None:
    db = tmp_path / "traces.sqlite3"
    first = TraceStore(backend="sqlite", db_path=db, retention_s=3600)
    first.finish(_trace("persist"))
    first.close()
    second = TraceStore(backend="sqlite", db_path=db, retention_s=3600)
    assert second.get("persist") is not None
    assert second.cleanup(now=time.time() + 7200) == 1  # two hours later it has expired
    assert second.get("persist") is None
    second.close()


def test_sqlite_skips_malformed_rows(tmp_path: Path) -> None:
    db = tmp_path / "traces.sqlite3"
    store = TraceStore(backend="sqlite", db_path=db)
    store.finish(_trace("good"))
    with sqlite3.connect(db) as conn:
        conn.execute("INSERT INTO traces VALUES ('bad', ?, 'ok', '{not json')", (time.time(),))
    ids = [t.trace_id for t in store.recent(10)]
    assert ids == ["good"]
    assert store.get("bad") is None
    store.close()
