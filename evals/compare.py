"""Compare two saved evaluation runs (agent or retrieval) and list regressions and improvements.

Usage (repository root):
    python -m evals.compare RUN_A RUN_B          # run ids or paths; ids are looked up in evals/reports/runs
    python -m evals.compare --list               # list saved runs with their configuration

Runs are only comparable when they used the same dataset; a warning is printed otherwise, and a
mock run is never presented as equivalent to a live-model run.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

RUNS = Path(__file__).resolve().parent / "reports" / "runs"
AGENT_METRICS = [
    "pass_rate", "tool_selection_accuracy", "server_selection_accuracy", "argument_accuracy", "answer_correctness",
    "citation_correctness", "source_mode_accuracy", "unnecessary_tool_call_rate", "repeated_tool_call_rate",
    "failure_recovery_rate", "llm_turns_mean", "latency_p50_ms", "latency_p95_ms", "first_token_p50_ms",
    "prompt_tokens", "completion_tokens",
]  # fmt: skip
LOWER_IS_BETTER = {"unnecessary_tool_call_rate", "repeated_tool_call_rate", "latency_p50_ms", "latency_p95_ms",
                   "first_token_p50_ms", "llm_turns_mean", "prompt_tokens", "completion_tokens",
                   "false_abstention_rate", "retrieve_p50_ms", "search_p50_ms", "search_p95_ms"}  # fmt: skip
RETRIEVAL_METRICS = ["recall@1", "recall@3", "recall@5", "mrr", "ndcg@5", "abstain_precision", "abstain_recall",
                     "false_abstention_rate", "top_citation_supported", "search_p50_ms", "search_p95_ms"]  # fmt: skip


def load(ref: str) -> dict[str, Any]:
    path = Path(ref)
    if not path.exists():
        path = RUNS / (ref if ref.endswith(".json") else f"{ref}.json")
    if not path.exists():
        raise SystemExit(f"Run not found: {ref}")
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8-sig"))
    return data


def list_runs() -> list[dict[str, Any]]:
    out = []
    for p in sorted(RUNS.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8-sig"))
        except ValueError:
            continue
        c = d.get("config") or {}
        out.append({
            "run_id": d.get("run_id") or p.stem,
            "kind": d.get("kind", "agent"),
            "generated_at": d.get("generated_at"),
            "dataset": d.get("dataset"),
            "provider": d.get("provider") or ",".join(r.get("retriever", "") for r in d.get("results", [])),
            "model": d.get("model"),
            "transport": d.get("transport"),
            "retriever": c.get("retriever"),
            "pass_rate": (d.get("summary") or {}).get("pass_rate"),
            "legacy": "legacy" in p.stem,
        })  # fmt: skip
    return out


def _delta(name: str, a: Any, b: Any) -> str:
    if not isinstance(a, int | float) or not isinstance(b, int | float):
        return ""
    d = b - a
    if abs(d) < 1e-9:
        return "="
    better = (d < 0) if name in LOWER_IS_BETTER else (d > 0)
    return f"{'+' if d > 0 else ''}{round(d, 4)} ({'better' if better else 'worse'})"


def compare_agent(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    lines = ["| Metric | A | B | Change |", "|---|---|---|---|"]
    for m in AGENT_METRICS:
        va, vb = a["summary"].get(m), b["summary"].get(m)
        lines.append(f"| {m} | {va} | {vb} | {_delta(m, va, vb)} |")
    by_a = {(r["id"], r.get("repeat", 1)): r for r in a["cases"]}
    by_b = {(r["id"], r.get("repeat", 1)): r for r in b["cases"]}
    regress = sorted(k[0] for k in by_a.keys() & by_b.keys() if by_a[k]["passed"] and not by_b[k]["passed"])
    improve = sorted(k[0] for k in by_a.keys() & by_b.keys() if not by_a[k]["passed"] and by_b[k]["passed"])
    lines += ["", f"Regressions (pass in A, fail in B): {', '.join(regress) or 'none'}",
              f"Improvements (fail in A, pass in B): {', '.join(improve) or 'none'}"]  # fmt: skip
    for cid in regress:
        row = next(r for r in b["cases"] if r["id"] == cid)
        lines.append(f"  - {cid}: {'; '.join(row['failures'])}")
    return lines


def compare_retrieval(a: dict[str, Any], b: dict[str, Any]) -> list[str]:
    lines = ["| Retriever | Metric (test) | A | B | Change |", "|---|---|---|---|---|"]
    ra = {r["retriever"]: r for r in a["results"] if r["status"] == "ok"}
    rb = {r["retriever"]: r for r in b["results"] if r["status"] == "ok"}
    for name in sorted(ra.keys() & rb.keys()):
        for m in RETRIEVAL_METRICS:
            va, vb = ra[name]["splits"]["test"].get(m), rb[name]["splits"]["test"].get(m)
            lines.append(f"| {name} | {m} | {va} | {vb} | {_delta(m, va, vb)} |")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("runs", nargs="*")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()
    if args.list or not args.runs:
        for r in list_runs():
            print(f"{r['run_id']:<55} {r['kind']:<9} {r['dataset'] or '':<26} {r['provider'] or '':<10} "
                  f"pass={r['pass_rate']}")  # fmt: skip
        return
    if len(args.runs) != 2:
        parser.error("give exactly two runs")
    a, b = load(args.runs[0]), load(args.runs[1])
    if a.get("kind", "agent") != b.get("kind", "agent"):
        raise SystemExit("Cannot compare an agent run with a retrieval run.")
    if a.get("dataset") != b.get("dataset"):
        print(f"WARNING: different datasets ({a.get('dataset')} vs {b.get('dataset')}); numbers are not comparable.",
              file=sys.stderr)  # fmt: skip
    if a.get("provider") != b.get("provider") and "mock" in (a.get("provider"), b.get("provider")):
        print("NOTE: one run uses the mock keyword router, the other a real model: tool-selection numbers are "
              "not measuring the same thing.", file=sys.stderr)  # fmt: skip
    print(f"A: {a.get('run_id')}\nB: {b.get('run_id')}\n")
    lines = compare_retrieval(a, b) if a.get("kind") == "retrieval" else compare_agent(a, b)
    print("\n".join(lines))


if __name__ == "__main__":
    main()
