"""Run a CampusOrchestrator agent benchmark and write an immutable run report.

Usage (from the repository root):
    python -m evals.run_eval                                   # v2 suite, mock provider, in-process MCP servers
    python -m evals.run_eval --dataset evals/datasets/campus_eval_v1.yaml   # the original v1 suite
    python -m evals.run_eval --transport http                  # MCP servers already running on localhost:810x
    python -m evals.run_eval --category failure --category llm_failure      # fault-injection cases only
    python -m evals.run_eval --repeat 3                        # repeated runs (stability)
    python -m evals.run_eval --retriever hybrid                # academics retrieval configuration (in-process)
    python -m evals.run_eval --provider groq --case acad-01 --yes-live      # LIVE GroqCloud (costs quota)

MockProvider is a deterministic keyword router, not a language model: its tool-selection numbers measure the
pipeline (discovery, routing, validation, retrieval, citations, failure handling), never GPT-OSS judgement.
Every number in a report is measured by this script; nothing is hand-entered. Each run is written to
evals/reports/runs/<run_id>.json (never overwritten); latest pointers are refreshed for full runs.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import statistics
import subprocess
import sys
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from app.agent.orchestrator import AgentLimits, Orchestrator  # noqa: E402
from app.agent.prompts import prompt_version  # noqa: E402
from app.agent.trace_store import TraceStore  # noqa: E402
from app.config import Settings  # noqa: E402
from app.llm.base import (  # noqa: E402
    ChatMessage,
    LLMProvider,
    LLMRateLimitError,
    LLMResponse,
    LLMTimeoutError,
    LLMToolCallFormatError,
    TextCallback,
    ToolCall,
    ToolSpec,
)
from app.llm.factory import build_provider  # noqa: E402
from app.llm.mock import MockProvider  # noqa: E402
from app.mcp.config import ServerConfig  # noqa: E402
from app.mcp.faults import FaultInjectingConnector  # noqa: E402
from app.mcp.manager import Connector, MCPClientManager, http_connector  # noqa: E402

SERVER_IDS = ["library", "events", "cafeteria", "academics"]
DEFAULT_DATASET = ROOT / "evals" / "datasets" / "campus_eval_v2.yaml"
REPLAY = ROOT / "evals" / "fixtures" / "public_books_replay.json"
LIVE_CONFIRM_THRESHOLD = 5  # live runs larger than this need --yes-live
MOCK_NOTE = (
    "Mock-provider run: tool choice comes from a deterministic keyword router, so tool-selection numbers measure "
    "the pipeline (MCP discovery, routing, validation, retrieval, citations, failure handling), not GPT-OSS-120B's "
    "judgement. Run with --provider groq for a live-model evaluation."
)


# ---------------------------------------------------------------------------------------------- servers
def _public_books_replay() -> Any:
    """DiscoveryService answering from recorded real API responses (offline, deterministic)."""
    import httpx

    from library_mcp.discovery import DiscoveryService, OpenLibraryProvider, OpenStaxProvider

    data = json.loads(REPLAY.read_text(encoding="utf-8"))

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.host == "openstax.org":
            return httpx.Response(200, json=data["openstax"])
        if request.url.host == "openlibrary.org":
            q = request.url.params.get("q", "").lower()
            if "chemistry" in q:
                return httpx.Response(503)  # recorded outage scenario for the partial-results case
            for key, payload in data["openlibrary"].items():
                if key in q:
                    return httpx.Response(200, json=payload)
            return httpx.Response(200, json={"numFound": 0, "docs": []})
        return httpx.Response(404)

    providers: list[Any] = [OpenLibraryProvider(), OpenStaxProvider()]
    for p in providers:
        p.min_interval_s = 0.0
    return DiscoveryService(providers, client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))


_ACADEMICS_CACHE: dict[tuple[str, str], Any] = {}


def build_inprocess_servers(
    now: datetime,
    tz: str = "Asia/Kolkata",
    fixtures: str = "v1",
    retriever: str = "hashing",
    extra: list[str] | tuple[str, ...] = (),
) -> dict[str, Any]:
    """The four real MCP servers, all sharing one fixed campus clock (deterministic evaluation)."""
    from academics_mcp.config import DEMO_HANDBOOK_DIR, OFFICIAL_DOC_DIR, AcademicsSettings
    from academics_mcp.server import build_server as academics
    from academics_mcp.server import build_service
    from cafeteria_mcp.campus_time import CampusClock as CafeteriaClock
    from cafeteria_mcp.provider import DEMO_MENU_PATH, MenuProvider, menu_from_json
    from cafeteria_mcp.server import build_server as cafeteria
    from events_mcp.campus_time import CampusClock as EventsClock
    from events_mcp.provider import DEMO_DATA_PATH as EVENTS_DATA
    from events_mcp.provider import DemoEventsProvider
    from events_mcp.server import build_server as events
    from library_mcp.campus_time import CampusClock as LibraryClock
    from library_mcp.provider import DEMO_DATA_PATH as LIB_DATA
    from library_mcp.provider import DemoLibraryProvider
    from library_mcp.server import build_server as library

    v1 = fixtures == "v1"
    menu = DEMO_MENU_PATH.with_name("demo_menu_v1.json") if v1 else DEMO_MENU_PATH
    books = LIB_DATA.with_name("demo_books_v1.json") if v1 else LIB_DATA
    evts = EVENTS_DATA.with_name("demo_events_v1.json") if v1 else EVENTS_DATA
    if v1:
        acad = AcademicsSettings(handbook_dir=DEMO_HANDBOOK_DIR, manifest_path=None, qdrant_path=":memory:")
    else:
        mode = "hybrid" if retriever.startswith("hybrid") else "dense"
        provider = "fastembed" if "fastembed" in retriever else "hashing"
        acad = AcademicsSettings.for_embedder(
            provider, handbook_dir=OFFICIAL_DOC_DIR, qdrant_path=":memory:", retrieval_mode=mode
        )
    key = (fixtures, retriever)
    if key not in _ACADEMICS_CACHE:  # the index does not depend on the clock: build it once per configuration
        _ACADEMICS_CACHE[key] = build_service(acad)
    servers: dict[str, Any] = {
        "library": library(
            DemoLibraryProvider(books, clock=LibraryClock.fixed(now, tz)),
            discovery=None if v1 else _public_books_replay(),
        ),
        "events": events(DemoEventsProvider(evts, clock=EventsClock.fixed(now, tz))),
        "cafeteria": cafeteria(
            MenuProvider(menu_from_json(menu), mode="demo", provider="demo-json", clock=CafeteriaClock.fixed(now, tz))
        ),
        "academics": academics(_ACADEMICS_CACHE[key]),
    }
    if "transport" in extra:
        from tests.fixtures.transport_mcp import build_server as transport

        servers["transport"] = transport()
    return servers


def inprocess_connector(servers: dict[str, Any]) -> Connector:
    from mcp import Client

    def connect(cfg: ServerConfig, timeout_s: float) -> Any:
        return Client(servers[cfg.id], read_timeout_seconds=timeout_s, cache=None)

    return connect


# ---------------------------------------------------------------------------------------------- LLM faults
class FaultyLLM:
    """Wraps a provider to inject model-side failures (measures our handling, not the model)."""

    def __init__(self, inner: LLMProvider, kind: str) -> None:
        self._inner = inner
        self._kind = kind
        self._calls = 0
        self.name = inner.name
        self.model = inner.model

    async def complete(
        self,
        messages: list[ChatMessage],
        tools: list[ToolSpec],
        *,
        on_text: TextCallback | None = None,
        allow_tools: bool = True,
    ) -> LLMResponse:
        self._calls += 1
        if self._kind == "rate_limit":
            raise LLMRateLimitError("Simulated HTTP 429 from the model provider.", retry_after_s=30)
        if self._kind == "timeout":
            raise LLMTimeoutError("Simulated model timeout.")
        if self._kind == "malformed_tool_call" and self._calls == 1:
            raise LLMToolCallFormatError("Simulated malformed tool call.")
        if self._kind == "unknown_tool":
            if self._calls == 1:
                call = ToolCall("bad_0", "nonexistent__teleport", "{}", {})
                return LLMResponse(content=None, tool_calls=[call], finish_reason="tool_calls", model=self.model)
            messages = [
                m for m in messages if m.tool_call_id != "bad_0" and not any(c.id == "bad_0" for c in m.tool_calls)
            ]
        if self._kind == "tool_loop":
            if not allow_tools:
                return LLMResponse(content="", tool_calls=[], finish_reason="stop", model=self.model)
            name = next(t.name for t in tools if t.name.endswith("get_today_menu"))
            call = ToolCall(f"loop_{self._calls}", name, "{}", {})
            return LLMResponse(content=None, tool_calls=[call], finish_reason="tool_calls", model=self.model)
        return await self._inner.complete(messages, tools, on_text=on_text, allow_tools=allow_tools)


# ---------------------------------------------------------------------------------------------- scoring
def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return round(ordered[idx], 1)


def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def _args_match(expected: dict[str, Any], actual: dict[str, Any] | None) -> bool:
    actual = actual or {}
    for key, value in expected.items():
        got = actual.get(key)
        if isinstance(value, str) and isinstance(got, str):
            if value.lower() not in got.lower():
                return False
        elif got != value:
            return False
    return True


LLM_INFRA_ERRORS = {"llm_rate_limited", "llm_timeout", "llm_unavailable", "llm_auth_failed", "llm_not_configured"}


def evaluate_case(case: dict[str, Any], result: Any, dataset_version: int = 1) -> dict[str, Any]:
    answer = result.answer.lower()
    called_servers = sorted({t.server_id for t in result.tool_calls if t.server_id})
    called_tools = sorted({t.tool for t in result.tool_calls if t.status != "unknown_tool"})
    failures: list[str] = []

    # --- tool / server selection
    if dataset_version >= 2 and "expected_tools" in case:
        tool_sets = [sorted(a) for a in case.get("acceptable_tools", [])] or [sorted(case["expected_tools"])]
        tool_ok = called_tools in tool_sets
        expected_tools = next((a for a in tool_sets if a == called_tools), tool_sets[0])
        if not tool_ok:
            failures.append(f"tools: expected {expected_tools or 'none'}, called {called_tools or 'none'}")
        server_sets = [sorted({t.split("__", 1)[0] for t in s}) for s in tool_sets]
        server_ok = called_servers in server_sets
        expected = next((s for s in server_sets if s == called_servers), server_sets[0])
        unnecessary = [t for t in result.tool_calls if t.tool not in expected_tools and t.status != "unknown_tool"]
    else:
        alternatives = [sorted(a) for a in case.get("acceptable_servers", [])] or [
            sorted(case.get("expected_servers", []))
        ]
        expected = next((a for a in alternatives if a == called_servers), alternatives[0])
        server_ok = called_servers in alternatives
        tool_ok = server_ok
        if not server_ok:
            failures.append(
                f"tools: expected {' or '.join(str(a or 'none') for a in alternatives)}, called {called_servers or 'none'}"
            )
        unnecessary = [t for t in result.tool_calls if t.server_id and t.server_id not in expected]

    # --- arguments
    args_ok: bool | None = None
    if exp_args := case.get("expected_args"):
        args_ok = True
        for tool, want in exp_args.items():
            calls = [t for t in result.tool_calls if t.tool == tool]
            if not any(_args_match(want, t.arguments) for t in calls):
                args_ok = False
                got = [t.arguments for t in calls] or "not called"
                failures.append(f"args: {tool} expected {want}, got {got}")

    # --- answer facts
    answer_ok = True
    for needle in case.get("must_contain", []):
        if needle.lower() not in answer:
            answer_ok = False
            failures.append(f"answer missing '{needle}'")
    any_of = case.get("must_contain_any")
    if any_of and not any(n.lower() in answer for n in any_of):
        answer_ok = False
        failures.append(f"answer contains none of {any_of}")
    for needle in case.get("must_not_contain", []):
        if needle.lower() in answer:
            answer_ok = False
            failures.append(f"answer contains forbidden '{needle}'")

    # --- citations / abstention
    citation_ok: bool | None = None
    targets = case.get("expected_citation_any") or (
        [case["expected_citation"]] if case.get("expected_citation") else []
    )
    if targets:
        match = any(c.source_filename == t["file"] and c.page == t["page"] for c in result.citations for t in targets)
        citation_ok = match and result.citation_check.ok
        if not match:
            got = [f"{c.source_filename}:p{c.page}" for c in result.citations] or ["none"]
            want = [f"{t['file']}:p{t['page']}" for t in targets]
            failures.append(f"citation: expected one of {want}, got {got[:3]}")
        if not result.citation_check.ok:
            failures.append(f"unsupported page refs {result.citation_check.unsupported}")
    if case.get("expect_insufficient"):
        citation_ok = bool(result.insufficient_evidence and not result.citations)
        if not citation_ok:
            failures.append("expected an insufficient-evidence result")

    # --- status and provenance
    status_ok = True
    if want_status := case.get("expect_status"):
        status_ok = result.status == want_status
        if not status_ok:
            failures.append(f"status: expected {want_status}, got {result.status}")
    modes_ok: bool | None = None
    if want_modes := case.get("expect_source_modes"):
        got_modes = {s.server_id: s.mode for s in result.sources}
        modes_ok = all(got_modes.get(k) == v for k, v in want_modes.items())
        if not modes_ok:
            failures.append(f"source modes: expected {want_modes}, got {got_modes}")

    recovered: bool | None = None
    if case.get("faults"):
        faulty = set(case["faults"])
        healthy = [t for t in result.tool_calls if t.server_id not in faulty]
        recovered = status_ok and answer_ok and all(t.status == "success" for t in healthy)

    keys = [f"{t.tool}:{json.dumps(t.arguments, sort_keys=True)}" for t in result.tool_calls]
    repeated = len(keys) - len(set(keys))
    budget = any(t.status == "budget_exceeded" for t in result.tool_calls) or result.error_code == "max_iterations"
    if result.error_code in LLM_INFRA_ERRORS and not case.get("llm_fault"):
        failure_class: str | None = "infra_llm"
    elif case.get("faults") or case.get("llm_fault"):
        failure_class = "fault_handling" if failures else None
    else:
        failure_class = "reasoning" if failures else None

    timings = result.timings
    return {
        "id": case["id"],
        "category": case["category"],
        "query": case["query"],
        "passed": not failures,
        "failures": failures,
        "failure_class": failure_class,
        "expected_servers": expected,
        "called_servers": called_servers,
        "called_tools": called_tools,
        "tool_selection_correct": tool_ok,
        "server_selection_correct": server_ok,
        "arguments_correct": args_ok,
        "unnecessary_calls": len(unnecessary),
        "repeated_calls": repeated,
        "total_calls": len(result.tool_calls),
        "answer_correct": answer_ok,
        "citation_correct": citation_ok,
        "source_modes_correct": modes_ok,
        "recovered": recovered,
        "budget_exhausted": budget,
        "status": result.status,
        "error_code": result.error_code,
        "latency_ms": result.latency_ms,
        "timings": timings.model_dump() if timings is not None else None,
        "tool_durations_ms": [c.duration_ms for c in result.tool_calls if not c.cached],
        "iterations": result.iterations,
        "usage": result.usage,
        "note": case.get("note"),
        "answer": result.answer,
    }


# ---------------------------------------------------------------------------------------------- running
def _fixed_clock(instant: datetime) -> Callable[[], datetime]:
    return lambda: instant


def _git() -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout
        return {"commit": commit, "dirty": bool(dirty.strip())}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "dirty": None}


def _select(
    cases: list[dict[str, Any]], args: argparse.Namespace, live: bool
) -> tuple[list[dict[str, Any]], list[str]]:
    skipped: list[str] = []
    out = []
    for c in cases:
        if args.case and c["id"] not in args.case:
            continue
        if args.category and c["category"] not in args.category:
            continue
        if live and c.get("llm_fault"):
            skipped.append(f"{c['id']} (llm_fault cases measure our handling; skipped on live runs)")
            continue
        if args.transport == "http" and c.get("extra_servers"):
            skipped.append(f"{c['id']} (needs the in-process test server)")
            continue
        out.append(c)
    return out[: args.limit or None], skipped


async def run(args: argparse.Namespace) -> dict[str, Any]:
    raw = await asyncio.to_thread(Path(args.dataset).read_bytes)
    dataset = yaml.safe_load(raw)
    version = int(dataset.get("version", 1))
    fixtures = dataset.get("fixtures", "v1")
    tz_name = dataset.get("timezone") or Settings().campus_timezone
    tz = ZoneInfo(tz_name)
    live = args.provider != "mock"
    cases, skipped = _select(dataset["cases"], args, live)

    if args.provider == "mock":
        base_llm: LLMProvider = MockProvider()
    else:
        settings = Settings(llm_provider="groq")
        if settings.groq_api_key is None:
            raise SystemExit("--provider groq requires GROQ_API_KEY in the environment or .env")
        base_llm = build_provider(settings)
        calls = len(cases) * args.repeat * 4
        print(
            f"LIVE evaluation: {len(cases)} cases x {args.repeat} repeat(s), up to ~{calls} GroqCloud requests "
            f"to {base_llm.model}. This consumes your Groq quota.",
            file=sys.stderr,
        )
        if len(cases) * args.repeat > LIVE_CONFIRM_THRESHOLD and not args.yes_live:
            raise SystemExit(f"Refusing a live run of more than {LIVE_CONFIRM_THRESHOLD} cases without --yes-live.")

    rows: list[dict[str, Any]] = []
    tool_hash = ""
    for rep in range(args.repeat):
        for case in cases:
            if args.transport == "inprocess":
                now = datetime.fromisoformat(case.get("clock") or dataset["clock"])
            else:
                now = datetime.now(tz)
            extra = list(case.get("extra_servers", []))
            if args.transport == "inprocess":
                base_connector = inprocess_connector(
                    build_inprocess_servers(now, tz_name, fixtures, args.retriever, extra)
                )
                configs = [ServerConfig(id=i, name=i.title(), url=f"inprocess://{i}") for i in SERVER_IDS + extra]
            else:
                base_connector = http_connector
                configs = [
                    ServerConfig(
                        id=i, name=i.title(), url=os.getenv(f"MCP_{i.upper()}_URL", f"http://localhost:810{n}/mcp")
                    )
                    for n, i in enumerate(SERVER_IDS, start=1)
                ]
            faults = case.get("faults") or {}
            connector: Connector = base_connector
            if faults:
                scope = case.get("fault_scope", "calls")
                connector = FaultInjectingConnector(base_connector, faults, scope=scope, hang_s=60)
            manager = MCPClientManager(configs, connector=connector, default_timeout_s=args.tool_timeout, max_retries=1)
            llm: LLMProvider = FaultyLLM(base_llm, case["llm_fault"]) if case.get("llm_fault") else base_llm
            orch = Orchestrator(llm, manager, TraceStore(), AgentLimits(), timezone=tz_name, clock=_fixed_clock(now))
            result = await orch.run(case["query"])
            if not tool_hash and manager.tools:
                spec = [(t.qualified_name, t.input_schema) for t in manager.tools if t.server_id in SERVER_IDS]
                tool_hash = hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:12]
            row = evaluate_case(case, result, version)
            row["repeat"] = rep + 1
            rows.append(row)
            mark = "PASS" if row["passed"] else "FAIL"
            print(f"{mark} {case['id']:<10} r{rep + 1} {row['latency_ms']:>7.0f} ms  {'; '.join(row['failures'])}")
            if args.delay:
                await asyncio.sleep(args.delay)

    generated = datetime.now(UTC)
    groq = Settings()
    config: dict[str, Any] = {
        "provider": base_llm.name,
        "model": base_llm.model,
        "model_settings": {}
        if base_llm.name == "mock"
        else {"temperature": groq.groq_temperature, "reasoning_effort": groq.groq_reasoning_effort},
        "prompt_version": prompt_version(),
        "tool_schema_hash": tool_hash,
        "dataset": Path(args.dataset).name,
        "dataset_version": version,
        "dataset_sha256": hashlib.sha256(raw).hexdigest()[:12],
        "fixtures": fixtures,
        "retriever": args.retriever if fixtures != "v1" else "hashing (v1 demo handbook)",
        "transport": args.transport,
        "repeat": args.repeat,
        "tool_timeout_s": args.tool_timeout,
        "timezone": tz_name,
        "clock": dataset.get("clock") if args.transport == "inprocess" else "live",
        "selection": {"case": args.case, "category": args.category, "limit": args.limit},
        "skipped": skipped,
        "git": _git(),
        "python": sys.version.split()[0],
        "platform": sys.platform,
    }
    digest = hashlib.sha256(json.dumps(config, sort_keys=True, default=str).encode()).hexdigest()[:6]
    run_id = f"agent-{generated.strftime('%Y%m%dT%H%M%SZ')}-{config['provider']}-{digest}"
    return build_report(rows, run_id, generated, config)


def build_report(
    rows: list[dict[str, Any]], run_id: str, generated: datetime, config: dict[str, Any]
) -> dict[str, Any]:
    first = [r for r in rows if r.get("repeat", 1) == 1]
    cite_rows = [r for r in rows if r["citation_correct"] is not None]
    fault_rows = [r for r in rows if r["recovered"] is not None]
    arg_rows = [r for r in rows if r["arguments_correct"] is not None]
    mode_rows = [r for r in rows if r["source_modes_correct"] is not None]
    total_calls = sum(r["total_calls"] for r in rows)
    ok_rows = [r for r in rows if r["status"] != "error"]
    lat_ok = [r["latency_ms"] for r in ok_rows]
    timings = [r["timings"] for r in rows if r["timings"]]
    first_tok = [t["first_token_ms"] for t in timings if t.get("first_token_ms") is not None]
    tool_durations = [d for r in rows for d in r["tool_durations_ms"]]
    categories: dict[str, dict[str, Any]] = {}
    for r in rows:
        c = categories.setdefault(r["category"], {"category": r["category"], "cases": 0, "passed": 0})
        c["cases"] += 1
        c["passed"] += int(r["passed"])
    stability = None
    if config["repeat"] > 1:
        outcomes: dict[str, set[bool]] = {}
        for r in rows:
            outcomes.setdefault(r["id"], set()).add(r["passed"])
        stability = {"cases": len(outcomes), "unstable": sorted(k for k, v in outcomes.items() if len(v) > 1)}
    n = len(lat_ok)
    summary = {
        "cases": len(first),
        "runs": len(rows),
        "passed": sum(r["passed"] for r in rows),
        "pass_rate": _ratio(sum(r["passed"] for r in rows), len(rows)),
        "tool_selection_accuracy": _ratio(sum(r["tool_selection_correct"] for r in rows), len(rows)),
        "server_selection_accuracy": _ratio(sum(r["server_selection_correct"] for r in rows), len(rows)),
        "argument_accuracy": _ratio(sum(bool(r["arguments_correct"]) for r in arg_rows), len(arg_rows)),
        "argument_cases": len(arg_rows),
        "answer_correctness": _ratio(sum(r["answer_correct"] for r in rows), len(rows)),
        "citation_correctness": _ratio(sum(bool(r["citation_correct"]) for r in cite_rows), len(cite_rows)),
        "citation_cases": len(cite_rows),
        "source_mode_accuracy": _ratio(sum(bool(r["source_modes_correct"]) for r in mode_rows), len(mode_rows)),
        "unnecessary_tool_call_rate": _ratio(sum(r["unnecessary_calls"] for r in rows), total_calls),
        "repeated_tool_call_rate": _ratio(sum(r["repeated_calls"] for r in rows), total_calls),
        "total_tool_calls": total_calls,
        "failure_recovery_rate": _ratio(sum(bool(r["recovered"]) for r in fault_rows), len(fault_rows)),
        "failure_cases": len(fault_rows),
        "budget_exhausted": sum(r["budget_exhausted"] for r in rows),
        "llm_turns_mean": round(statistics.fmean(r["iterations"] for r in rows), 2) if rows else None,
        "llm_infra_errors": sum(1 for r in rows if r["failure_class"] == "infra_llm"),
        "error_results": len(rows) - len(ok_rows),
        "failure_classes": {
            k: sum(1 for r in rows if r["failure_class"] == k) for k in ("reasoning", "fault_handling", "infra_llm")
        },
        "latency_sample": n,
        "latency_p50_ms": _pct(lat_ok, 0.5),
        "latency_p95_ms": _pct(lat_ok, 0.95),
        "latency_p99_ms": _pct(lat_ok, 0.99) if n >= 100 else None,
        "latency_mean_ms": round(statistics.fmean(lat_ok), 1) if lat_ok else None,
        "first_token_p50_ms": _pct(first_tok, 0.5),
        "first_token_sample": len(first_tok),
        "llm_wall_p50_ms": _pct([t["llm_wall_ms"] for t in timings], 0.5),
        "tool_wall_p50_ms": _pct([t["tool_wall_ms"] for t in timings], 0.5),
        "discovery_p50_ms": _pct([t["discovery_ms"] for t in timings], 0.5),
        "tool_duration_p50_ms": _pct(tool_durations, 0.5),
        "tool_duration_p95_ms": _pct(tool_durations, 0.95),
        "prompt_tokens": sum(r["usage"].get("prompt_tokens", 0) for r in rows),
        "completion_tokens": sum(r["usage"].get("completion_tokens", 0) for r in rows),
        "stability": stability,
    }
    return {
        "kind": "agent",
        "run_id": run_id,
        "generated_at": generated.isoformat(timespec="seconds"),
        "dataset": config["dataset"],
        "provider": config["provider"],
        "model": config["model"],
        "transport": config["transport"],
        "config": config,
        "note": MOCK_NOTE if config["provider"] == "mock" else "Live GroqCloud evaluation; results vary between runs.",
        "latency_note": (
            "Latency percentiles use requests that did not end in status=error; error and fault counts are reported "
            "separately. In-process transport has no network hop; the first case includes cold-start costs (no "
            "warm-up). p99 is reported only with at least 100 samples."
        ),
        "summary": summary,
        "categories": list(categories.values()),
        "cases": rows,
    }


def to_markdown(report: dict[str, Any]) -> str:
    s = report["summary"]
    c = report.get("config") or {}
    git = c.get("git") or {}

    def pct(v: float | None) -> str:
        return "n/a" if v is None else f"{v * 100:.1f}%"

    lines = [
        "# CampusOrchestrator evaluation report",
        "",
        f"- Run: `{report.get('run_id', '-')}` ({report['generated_at']})",
        f"- Dataset: `{report['dataset']}` v{c.get('dataset_version', 1)} ({s['cases']} cases x {c.get('repeat', 1)}), "
        f"fixtures {c.get('fixtures')}",
        f"- Provider / model: {report['provider']} / `{report['model']}`; transport: {report['transport']}; "
        f"retriever: {c.get('retriever')}",
        f"- Prompt {c.get('prompt_version')}, tool schemas {c.get('tool_schema_hash')}, commit "
        f"{str(git.get('commit'))[:10]}{' (uncommitted changes)' if git.get('dirty') else ''}",
        "",
        f"> {report['note']}",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Cases passed | {s['passed']}/{s['runs']} ({pct(s['pass_rate'])}) |",
        f"| Tool-selection accuracy (exact tool set) | {pct(s['tool_selection_accuracy'])} |",
        f"| Server-selection accuracy | {pct(s['server_selection_accuracy'])} |",
        f"| Argument accuracy ({s['argument_cases']} cases) | {pct(s['argument_accuracy'])} |",
        f"| Answer correctness (required facts present, forbidden absent) | {pct(s['answer_correctness'])} |",
        f"| Citation / abstention correctness ({s['citation_cases']} cases) | {pct(s['citation_correctness'])} |",
        f"| Source-mode labelling | {pct(s['source_mode_accuracy'])} |",
        f"| Unnecessary / repeated tool-call rate ({s['total_tool_calls']} calls) | "
        f"{pct(s['unnecessary_tool_call_rate'])} / {pct(s['repeated_tool_call_rate'])} |",
        f"| Recovery from injected MCP faults ({s['failure_cases']} cases) | {pct(s['failure_recovery_rate'])} |",
        f"| Tool budget exhausted | {s['budget_exhausted']} |",
        f"| Mean LLM turns | {s['llm_turns_mean']} |",
        f"| Results with status=error / model infrastructure errors | {s['error_results']} / {s['llm_infra_errors']} |",
        f"| Latency p50 / p95 / p99 (n={s['latency_sample']}, non-error) | {s['latency_p50_ms']} / "
        f"{s['latency_p95_ms']} / {s['latency_p99_ms'] or 'n/a'} ms |",
        f"| First token p50 (n={s['first_token_sample']}) | {s['first_token_p50_ms']} ms |",
        f"| LLM wall p50 / tool wall p50 / discovery p50 | {s['llm_wall_p50_ms']} / {s['tool_wall_p50_ms']} / "
        f"{s['discovery_p50_ms']} ms |",
        f"| Tokens (prompt / completion) | {s['prompt_tokens']} / {s['completion_tokens']} |",
        "",
        f"_{report.get('latency_note', '')}_",
        "",
        "## By category",
        "",
        "| Category | Passed |",
        "|---|---|",
        *[f"| {cat['category']} | {cat['passed']}/{cat['cases']} |" for cat in report["categories"]],
        "",
        "## Failed cases",
        "",
    ]
    failed = [r for r in report["cases"] if not r["passed"]]
    if not failed:
        lines.append("None.")
    for r in failed:
        lines.append(f"- **{r['id']}** ({r['category']}, {r.get('failure_class')}): {r['query']}")
        for f in r["failures"]:
            lines.append(f"  - {f}")
        if r.get("note"):
            lines.append(f"  - note: {r['note']}")
    if c.get("skipped"):
        lines += ["", "## Skipped", "", *[f"- {item}" for item in c["skipped"]]]
    return "\n".join(lines) + "\n"


def write_report(report: dict[str, Any], out: Path, full_run: bool) -> Path:
    runs = out / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    path = runs / f"{report['run_id']}.json"
    path.write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    if full_run:
        c = report["config"]
        # "latest" = the default configuration (v2, mock, in-process, hashing, single run); others get
        # descriptive pointers so they never overwrite it.
        parts = ["latest"]
        if c.get("dataset_version", 1) == 1:
            parts.append("v1")
        if report["provider"] != "mock":
            parts.append(report["provider"])
        if report["transport"] == "http":
            parts.append("http")
        if c.get("dataset_version", 1) >= 2 and c.get("retriever") not in (None, "hashing"):
            parts.append(str(c["retriever"]))
        if c.get("repeat", 1) > 1:
            parts.append(f"repeat{c['repeat']}")
        stem = "-".join(parts)
        (out / f"{stem}.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
        (out / f"{stem}.md").write_text(to_markdown(report), encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", choices=["mock", "groq"], default="mock")
    parser.add_argument("--transport", choices=["inprocess", "http"], default="inprocess")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--out", default=str(ROOT / "evals" / "reports"))
    parser.add_argument("--case", action="append", help="Run only this case id (repeatable)")
    parser.add_argument("--category", action="append", help="Run only this category (repeatable)")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--repeat", type=int, default=1, help="Run every selected case N times")
    parser.add_argument(
        "--retriever", default="hashing", choices=["hashing", "hybrid", "fastembed", "hybrid-fastembed"]
    )
    parser.add_argument("--delay", type=float, default=0.0, help="Seconds to wait between cases (rate limits)")
    parser.add_argument("--tool-timeout", type=float, default=2.0)
    parser.add_argument(
        "--yes-live", action="store_true", help=f"Allow live runs of more than {LIVE_CONFIRM_THRESHOLD} cases"
    )
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be >= 1")

    import logging

    logging.basicConfig(level=logging.WARNING)
    logging.getLogger("academics_mcp").setLevel(logging.WARNING)
    started = time.perf_counter()
    report = asyncio.run(run(args))
    full = not args.case and not args.category and not args.limit
    path = write_report(report, Path(args.out), full)
    s = report["summary"]
    print(f"\n{s['passed']}/{s['runs']} passed in {time.perf_counter() - started:.1f}s -> {path}")


if __name__ == "__main__":
    main()
