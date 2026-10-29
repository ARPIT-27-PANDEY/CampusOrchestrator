"""API tests: validation, stable error format, SSE protocol, traces, sources, CORS, limits."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.llm.base import LLMRateLimitError
from app.llm.mock import MockProvider, ScriptedProvider
from app.main import create_app
from app.state import build_state

from .fakes import FakeConnector, academics_server, configs, library_server


def make_client(llm: Any = None, **overrides: Any) -> TestClient:
    settings = Settings(llm_provider="mock", cors_origins="http://localhost:3000", **overrides)
    servers = {"library": library_server(), "academics": academics_server()}
    state = build_state(
        settings, connector=FakeConnector(servers), llm=llm or MockProvider(), servers=configs(*servers)
    )
    return TestClient(create_app(state=state))


@pytest.fixture
def client() -> Iterator[TestClient]:
    with make_client() as c:
        yield c


def parse_sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    events = []
    for block in text.strip().split("\n\n"):
        lines = [ln for ln in block.splitlines() if not ln.startswith(":")]
        if not lines:
            continue
        kind = next(ln[7:] for ln in lines if ln.startswith("event: "))
        data = json.loads(next(ln[6:] for ln in lines if ln.startswith("data: ")))
        events.append((kind, data))
    return events


def test_health(client: TestClient) -> None:
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert body["llm"] == {"provider": "mock", "model": "mock-deterministic-v1", "configured": True, "error": None}
    assert body["mcp"] == {"configured": 2, "available": 2, "tools": 3}


def test_chat_returns_answer_sources_and_trace(client: TestClient) -> None:
    resp = client.post("/api/chat", json={"message": "Is Introduction to Algorithms available?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert [t["tool"] for t in body["tool_calls"]] == ["library__search_books", "library__get_book_availability"]
    trace = client.get(f"/api/traces/{body['trace_id']}").json()
    assert trace["result"]["answer"] == body["answer"]
    listing = client.get("/api/traces").json()
    assert listing[0]["trace_id"] == body["trace_id"]


@pytest.mark.parametrize("payload", [{}, {"message": ""}, {"message": "   "}, {"message": 5}, {"msg": "hi"}])
def test_invalid_requests_use_stable_error_format(client: TestClient, payload: dict[str, Any]) -> None:
    resp = client.post("/api/chat", json=payload)
    assert resp.status_code == 422
    err = resp.json()["error"]
    assert err["code"] == "invalid_request" and err["request_id"]
    assert "Traceback" not in resp.text


def test_query_length_limit() -> None:
    with make_client(max_query_chars=20) as c:
        resp = c.post("/api/chat", json={"message": "x" * 21})
    assert resp.status_code == 422 and resp.json()["error"]["code"] == "query_too_long"


def test_body_size_limit() -> None:
    with make_client(max_request_bytes=100) as c:
        resp = c.post(
            "/api/chat", content=json.dumps({"message": "x" * 500}), headers={"content-type": "application/json"}
        )
    assert resp.status_code == 413 and resp.json()["error"]["code"] == "payload_too_large"


def test_unknown_route_and_trace(client: TestClient) -> None:
    assert client.get("/api/nope").json()["error"]["code"] == "not_found"
    assert client.get("/api/traces/doesnotexist").json()["error"]["code"] == "trace_not_found"


def test_sse_stream_protocol(client: TestClient) -> None:
    with client.stream(
        "POST", "/api/chat/stream", json={"message": "What is the AI workshop prerequisite in the handbook?"}
    ) as resp:
        assert resp.headers["content-type"].startswith("text/event-stream")
        text = "".join(resp.iter_text())
    events = parse_sse(text)
    kinds = [k for k, _ in events]
    assert kinds[0] == "start" and kinds[-2:] == ["final", "done"]
    assert "tool_start" in kinds and "tool_end" in kinds and "token" in kinds
    final = dict(events)["final"]
    streamed = "".join(d["text"] for k, d in events if k == "token")
    assert streamed.strip() == final["answer"]
    assert final["citations"][0]["page"] == 4


def test_sse_stream_reports_llm_errors_without_breaking_protocol() -> None:
    llm = ScriptedProvider([LLMRateLimitError("Groq rate limit reached; try again shortly.")])
    with make_client(llm=llm) as c, c.stream("POST", "/api/chat/stream", json={"message": "hi"}) as resp:
        events = parse_sse("".join(resp.iter_text()))
    kinds = [k for k, _ in events]
    assert "error" in kinds and kinds[-2:] == ["final", "done"]
    assert dict(events)["final"]["error_code"] == "llm_rate_limited"


def test_fault_injection_disabled_by_default(client: TestClient) -> None:
    resp = client.post("/api/chat", json={"message": "hi", "simulate_failures": {"library": "down"}})
    assert resp.status_code == 403 and resp.json()["error"]["code"] == "fault_injection_disabled"


def test_fault_injection_yields_partial_result() -> None:
    with make_client(allow_fault_injection=True) as c:
        body = c.post(
            "/api/chat",
            json={
                "message": "Is Introduction to Algorithms available, and what does the handbook say about the AI workshop prerequisite?",
                "simulate_failures": {"library": "down"},
            },
        ).json()
        assert body["status"] == "partial"
        assert body["citations"], "academics result survives the library failure"
        # the shared registry is untouched by per-request fault injection
        assert all(s["status"] == "available" for s in c.get("/api/sources").json()["servers"])


def test_sources_and_tools(client: TestClient) -> None:
    sources = client.get("/api/sources?refresh=true").json()
    assert {s["id"]: s["status"] for s in sources["servers"]} == {"library": "available", "academics": "available"}
    tools = client.get("/api/tools").json()
    assert {t["name"] for t in tools} == {
        "library__search_books",
        "library__get_book_availability",
        "academics__search_handbook",
    }


def test_cors_allows_only_configured_origin(client: TestClient) -> None:
    ok = client.options(
        "/api/chat", headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"}
    )
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:3000"
    bad = client.options("/api/chat", headers={"Origin": "http://evil.test", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in bad.headers


def test_eval_report_endpoint(tmp_path: Path) -> None:
    with make_client(eval_report_path=tmp_path / "missing.json") as c:
        assert c.get("/api/evals/latest").json()["error"]["code"] == "no_eval_report"
    report = tmp_path / "r.json"
    report.write_text(json.dumps({"summary": {"cases": 1}}))
    with make_client(eval_report_path=report) as c:
        assert c.get("/api/evals/latest").json()["summary"]["cases"] == 1


def test_eval_runs_keep_their_kind(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    runs.mkdir()
    reports = {
        "agent-1": {"kind": "agent", "generated_at": "2026-10-29T01:00:00+00:00", "provider": "mock",
                    "summary": {"pass_rate": 0.9, "cases": 66}},
        "retrieval-1": {"kind": "retrieval", "generated_at": "2026-10-29T02:00:00+00:00",
                        "results": [{"retriever": "hashing"}, {"retriever": "fastembed"}]},
        "library-1": {"kind": "library_search", "generated_at": "2026-10-29T03:00:00+00:00",
                      "results": [{"mode": "keyword"}, {"mode": "hybrid-fastembed"}]},
        "other-1": {"kind": "something_new", "generated_at": "2026-10-29T04:00:00+00:00"},
    }  # fmt: skip
    for run_id, body in reports.items():
        (runs / f"{run_id}.json").write_text(json.dumps({"run_id": run_id, **body}))
    with make_client(eval_report_path=tmp_path / "latest.json") as c:
        listed = {r["run_id"]: r for r in c.get("/api/evals/runs").json()}
        assert set(listed) == {"agent-1", "retrieval-1", "library-1"}  # unknown kinds are not shown as agent runs
        assert listed["library-1"]["kind"] == "library_search"
        assert listed["library-1"]["provider"] == "keyword,hybrid-fastembed"
        assert listed["retrieval-1"]["provider"] == "hashing,fastembed"
        assert c.get("/api/evals/runs/library-1").json()["kind"] == "library_search"


def test_groq_without_key_is_reported_not_silently_replaced() -> None:
    settings = Settings(llm_provider="groq", groq_api_key=None)
    state = build_state(settings, connector=FakeConnector({"library": library_server()}), servers=configs("library"))
    with TestClient(create_app(state=state)) as c:
        health = c.get("/api/health").json()
        assert health["status"] == "degraded" and health["llm"]["configured"] is False
        body = c.post("/api/chat", json={"message": "hi"}).json()
        assert body["status"] == "error" and body["error_code"] == "llm_not_configured"


def test_secrets_never_in_responses() -> None:
    settings = Settings(llm_provider="groq", groq_api_key="gsk_supersecretvalue123")
    state = build_state(settings, connector=FakeConnector({"library": library_server()}), servers=configs("library"))
    with TestClient(create_app(state=state)) as c:
        assert "gsk_supersecretvalue123" not in c.get("/api/health").text
