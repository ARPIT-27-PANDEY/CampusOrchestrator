"""Run the CampusOS evaluation set and write evals/reports/latest.{json,md}.

Usage (from the repository root):
    python -m evals.run_eval                          # mock LLM, in-process MCP servers (deterministic, free)
    python -m evals.run_eval --transport http         # mock LLM, MCP servers already running on localhost:810x
    python -m evals.run_eval --provider groq --delay 3   # LIVE GroqCloud calls (needs GROQ_API_KEY; costs quota)

The mock provider is a deterministic keyword router: its scores validate the MCP
plumbing, RAG retrieval, citations and failure handling, not GPT-OSS's tool selection.
Every number in the report is measured by this script; nothing is hand-entered.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.agent.orchestrator import AgentLimits, Orchestrator  # noqa: E402
from app.agent.trace_store import TraceStore  # noqa: E402
from app.config import Settings  # noqa: E402
from app.llm.base import LLMProvider  # noqa: E402
from app.llm.factory import build_provider  # noqa: E402
from app.llm.mock import MockProvider  # noqa: E402
from app.mcp.config import ServerConfig  # noqa: E402
from app.mcp.faults import FaultInjectingConnector  # noqa: E402
from app.mcp.manager import Connector, MCPClientManager, http_connector  # noqa: E402

SERVER_IDS = ["library", "events", "cafeteria", "academics"]
MOCK_NOTE = (
    "Mock-provider run: tool choice comes from a deterministic keyword router, so tool-selection numbers measure "
    "the pipeline (MCP discovery, routing, validation, retrieval, citations, failure handling), not GPT-OSS-120B's "
    "judgement. Run with --provider groq for a live-model evaluation."
)


def build_inprocess_servers(now: datetime) -> dict[str, Any]:
    from academics_mcp.config import AcademicsSettings
    from academics_mcp.server import build_server as academics
    from academics_mcp.server import build_service
    from cafeteria_mcp.provider import DEMO_MENU_PATH, MenuProvider, menu_from_json
    from cafeteria_mcp.server import build_server as cafeteria
    from events_mcp.provider import DemoEventsProvider
    from events_mcp.server import build_server as events
    from library_mcp.server import build_server as library

    today: date = now.date()
    return {
        "library": library(),
        "events": events(DemoEventsProvider(clock=lambda: now)),
        "cafeteria": cafeteria(
            MenuProvider(menu_from_json(DEMO_MENU_PATH), mode="demo", provider="demo-json", today=lambda: today)
        ),
        "academics": academics(build_service(AcademicsSettings(qdrant_path=":memory:"))),
    }


def inprocess_connector(servers: dict[str, Any]) -> Connector:
    from mcp import Client

    def connect(cfg: ServerConfig, timeout_s: float) -> Any:
        return Client(servers[cfg.id], read_timeout_seconds=timeout_s, cache=None)

    return connect


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, round(q * (len(ordered) - 1))))
    return round(ordered[idx], 1)


def _ratio(num: int, den: int) -> float | None:
    return round(num / den, 4) if den else None


def evaluate_case(case: dict[str, Any], result: Any) -> dict[str, Any]:
    answer = result.answer.lower()
    called = sorted({t.server_id for t in result.tool_calls if t.server_id})
    alternatives = [sorted(a) for a in case.get("acceptable_servers", [])] or [sorted(case.get("expected_servers", []))]
    expected = next((a for a in alternatives if a == called), alternatives[0])
    failures: list[str] = []

    tool_ok = called in alternatives
    if not tool_ok:
        failures.append(
            f"tools: expected {' or '.join(str(a or 'none') for a in alternatives)}, called {called or 'none'}"
        )
    unnecessary = [t for t in result.tool_calls if t.server_id and t.server_id not in expected]

    answer_ok = True
    for needle in case.get("must_contain", []):
        if needle.lower() not in answer:
            answer_ok = False
            failures.append(f"answer missing '{needle}'")
    for needle in case.get("must_not_contain", []):
        if needle.lower() in answer:
            answer_ok = False
            failures.append(f"answer contains forbidden '{needle}'")

    citation_ok: bool | None = None
    if exp := case.get("expected_citation"):
        match = any(c.source_filename == exp["file"] and c.page == exp["page"] for c in result.citations)
        citation_ok = match and result.citation_check.ok
        if not match:
            got = [f"{c.source_filename}:p{c.page}" for c in result.citations] or ["none"]
            failures.append(f"citation: expected {exp['file']}:p{exp['page']}, got {', '.join(got)}")
        if not result.citation_check.ok:
            failures.append(f"unsupported page refs {result.citation_check.unsupported}")
    if case.get("expect_insufficient"):
        insufficient_ok = result.insufficient_evidence and not result.citations
        citation_ok = insufficient_ok
        if not insufficient_ok:
            failures.append("expected an insufficient-evidence result")

    status_ok = True
    if want := case.get("expect_status"):
        status_ok = result.status == want
        if not status_ok:
            failures.append(f"status: expected {want}, got {result.status}")

    recovered: bool | None = None
    if case.get("faults"):
        faulty = set(case["faults"])
        healthy_calls = [t for t in result.tool_calls if t.server_id not in faulty]
        recovered = status_ok and answer_ok and all(t.status == "success" for t in healthy_calls)

    return {
        "id": case["id"],
        "category": case["category"],
        "query": case["query"],
        "passed": not failures,
        "failures": failures,
        "expected_servers": expected,
        "called_servers": called,
        "tool_selection_correct": tool_ok,
        "unnecessary_calls": len(unnecessary),
        "total_calls": len(result.tool_calls),
        "answer_correct": answer_ok,
        "citation_correct": citation_ok,
        "recovered": recovered,
        "status": result.status,
        "latency_ms": result.latency_ms,
        "tool_durations_ms": [t.duration_ms for t in result.tool_calls if not t.cached],
        "iterations": result.iterations,
        "usage": result.usage,
        "note": case.get("note"),
        "answer": result.answer,
    }


async def run(args: argparse.Namespace) -> dict[str, Any]:
    dataset = yaml.safe_load(await asyncio.to_thread(Path(args.dataset).read_text, encoding="utf-8"))
    tz = ZoneInfo("Asia/Kolkata")
    now = datetime.fromisoformat(dataset["clock"]) if args.transport == "inprocess" else datetime.now(tz)
    cases = [c for c in dataset["cases"] if not args.case or c["id"] in args.case][: args.limit or None]

    if args.provider == "mock":
        llm: LLMProvider = MockProvider()
    else:
        settings = Settings(llm_provider="groq")
        if settings.groq_api_key is None:
            raise SystemExit("--provider groq requires GROQ_API_KEY in the environment or .env")
        llm = build_provider(settings)
        print(f"LIVE evaluation: up to {len(cases) * 6} GroqCloud requests to {llm.model}.", file=sys.stderr)

    if args.transport == "inprocess":
        base_connector = inprocess_connector(build_inprocess_servers(now))
        configs = [ServerConfig(id=i, name=i.title(), url=f"inprocess://{i}") for i in SERVER_IDS]
    else:
        base_connector = http_connector
        configs = [
            ServerConfig(id=i, name=i.title(), url=os.getenv(f"MCP_{i.upper()}_URL", f"http://localhost:810{n}/mcp"))
            for n, i in enumerate(SERVER_IDS, start=1)
        ]

    rows = []
    for case in cases:
        faults = case.get("faults") or {}
        connector: Connector = (
            FaultInjectingConnector(base_connector, faults, scope=case.get("fault_scope", "calls"))
            if faults
            else base_connector
        )
        manager = MCPClientManager(configs, connector=connector, default_timeout_s=args.tool_timeout, max_retries=1)
        orch = Orchestrator(llm, manager, TraceStore(), AgentLimits(), clock=lambda: now)
        result = await orch.run(case["query"])
        row = evaluate_case(case, result)
        rows.append(row)
        mark = "PASS" if row["passed"] else "FAIL"
        print(f"{mark} {case['id']:<10} {row['latency_ms']:>7.0f} ms  {'; '.join(row['failures'])}")
        if args.delay:
            await asyncio.sleep(args.delay)

    return build_report(rows, llm, args)


def build_report(rows: list[dict[str, Any]], llm: LLMProvider, args: argparse.Namespace) -> dict[str, Any]:
    cite_rows = [r for r in rows if r["citation_correct"] is not None]
    fault_rows = [r for r in rows if r["recovered"] is not None]
    total_calls = sum(r["total_calls"] for r in rows)
    latencies = [r["latency_ms"] for r in rows]
    tool_durations = [d for r in rows for d in r["tool_durations_ms"]]
    categories: dict[str, dict[str, Any]] = {}
    for r in rows:
        c = categories.setdefault(r["category"], {"category": r["category"], "cases": 0, "passed": 0})
        c["cases"] += 1
        c["passed"] += int(r["passed"])
    summary = {
        "cases": len(rows),
        "passed": sum(r["passed"] for r in rows),
        "pass_rate": _ratio(sum(r["passed"] for r in rows), len(rows)),
        "tool_selection_accuracy": _ratio(sum(r["tool_selection_correct"] for r in rows), len(rows)),
        "answer_correctness": _ratio(sum(r["answer_correct"] for r in rows), len(rows)),
        "citation_correctness": _ratio(sum(bool(r["citation_correct"]) for r in cite_rows), len(cite_rows)),
        "citation_cases": len(cite_rows),
        "unnecessary_tool_call_rate": _ratio(sum(r["unnecessary_calls"] for r in rows), total_calls),
        "total_tool_calls": total_calls,
        "failure_recovery_rate": _ratio(sum(bool(r["recovered"]) for r in fault_rows), len(fault_rows)),
        "failure_cases": len(fault_rows),
        "latency_p50_ms": _pct(latencies, 0.5),
        "latency_p95_ms": _pct(latencies, 0.95),
        "latency_mean_ms": round(statistics.fmean(latencies), 1) if latencies else None,
        "tool_duration_p50_ms": _pct(tool_durations, 0.5),
        "tool_duration_p95_ms": _pct(tool_durations, 0.95),
        "prompt_tokens": sum(r["usage"].get("prompt_tokens", 0) for r in rows),
        "completion_tokens": sum(r["usage"].get("completion_tokens", 0) for r in rows),
    }
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "dataset": Path(args.dataset).name,
        "provider": llm.name,
        "model": llm.model,
        "transport": args.transport,
        "note": MOCK_NOTE if llm.name == "mock" else "Live GroqCloud evaluation; results vary between runs.",
        "summary": summary,
        "categories": list(categories.values()),
        "cases": rows,
    }


def to_markdown(report: dict[str, Any]) -> str:
    s = report["summary"]

    def pct(v: float | None) -> str:
        return "n/a" if v is None else f"{v * 100:.1f}%"

    lines = [
        "# CampusOS evaluation report",
        "",
        f"- Generated: {report['generated_at']}",
        f"- Dataset: `{report['dataset']}` ({s['cases']} cases)",
        f"- Provider / model: {report['provider']} / `{report['model']}`; MCP transport: {report['transport']}",
        "",
        f"> {report['note']}",
        "",
        "| Metric | Value |",
        "|---|---|",
        f"| Cases passed | {s['passed']}/{s['cases']} ({pct(s['pass_rate'])}) |",
        f"| Tool-selection accuracy (exact server set) | {pct(s['tool_selection_accuracy'])} |",
        f"| Answer correctness (required facts present, forbidden absent) | {pct(s['answer_correctness'])} |",
        f"| Citation correctness ({s['citation_cases']} cases) | {pct(s['citation_correctness'])} |",
        f"| Unnecessary tool-call rate ({s['total_tool_calls']} calls) | {pct(s['unnecessary_tool_call_rate'])} |",
        f"| Recovery from simulated failures ({s['failure_cases']} cases) | {pct(s['failure_recovery_rate'])} |",
        f"| End-to-end latency p50 / p95 | {s['latency_p50_ms']} ms / {s['latency_p95_ms']} ms |",
        f"| Tool-call duration p50 / p95 | {s['tool_duration_p50_ms']} ms / {s['tool_duration_p95_ms']} ms |",
        "",
        "## By category",
        "",
        "| Category | Passed |",
        "|---|---|",
        *[f"| {c['category']} | {c['passed']}/{c['cases']} |" for c in report["categories"]],
        "",
        "## Failed cases",
        "",
    ]
    failed = [r for r in report["cases"] if not r["passed"]]
    if not failed:
        lines.append("None.")
    for r in failed:
        lines.append(f"- **{r['id']}** ({r['category']}): {r['query']}")
        for f in r["failures"]:
            lines.append(f"  - {f}")
        if r.get("note"):
            lines.append(f"  - note: {r['note']}")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--provider", choices=["mock", "groq"], default="mock")
    parser.add_argument("--transport", choices=["inprocess", "http"], default="inprocess")
    parser.add_argument("--dataset", default=str(ROOT / "evals" / "datasets" / "campus_eval_v1.yaml"))
    parser.add_argument("--out", default=str(ROOT / "evals" / "reports"))
    parser.add_argument("--case", action="append", help="Run only this case id (repeatable)")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--delay", type=float, default=0.0, help="Seconds to wait between cases (rate limits)")
    parser.add_argument("--tool-timeout", type=float, default=2.0)
    args = parser.parse_args()

    started = time.perf_counter()
    report = asyncio.run(run(args))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stem = "latest" if not args.case and not args.limit else "partial"
    if stem == "latest" and report["provider"] != "mock":
        stem = "latest-groq"
    elif stem == "latest" and report["transport"] == "http":
        stem = "latest-http"
    (out / f"{stem}.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    (out / f"{stem}.md").write_text(to_markdown(report), encoding="utf-8")
    s = report["summary"]
    print(f"\n{s['passed']}/{s['cases']} passed in {time.perf_counter() - started:.1f}s -> {out / stem}.json")


if __name__ == "__main__":
    main()
