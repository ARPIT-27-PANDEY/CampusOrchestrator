"""Library catalogue search benchmark: keyword tiers vs hybrid (keyword + embeddings, RRF).

Usage (repository root):
    python -m evals.run_library_search                      # keyword, hybrid-hashing, hybrid-fastembed; default gates
    python -m evals.run_library_search --tune               # choose gates on the dev split, then score test
    python -m evals.run_library_search --modes keyword --query p01 --query n03    # debugging; no report

Every mode searches the same catalogue with the same queries through DemoLibraryProvider.search, the
code path the search_books MCP tool uses. With --tune, the semantic gates (min_score, min_z) are chosen on
the dev split only and applied unchanged to test. hybrid-fastembed is reported as "not_run" (never copied
from another mode) when the optional dependency or model is unavailable.

Outputs: an immutable run file in evals/reports/runs/ and evals/reports/library-latest.{json,md}.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "library_mcp"))

from library_mcp.provider import DEMO_DATA_PATH, DemoLibraryProvider  # noqa: E402
from library_mcp.semantic import (  # noqa: E402
    DEFAULT_MIN_SCORE,
    DEFAULT_MIN_Z,
    Embedder,
    EmbedderUnavailableError,
    SemanticIndex,
    build_embedder,
)

DATASET = ROOT / "evals" / "datasets" / "library_search_v1.yaml"
REPORTS = ROOT / "evals" / "reports"
MODES = {"keyword": None, "hybrid-hashing": "hashing", "hybrid-fastembed": "fastembed"}
GRID_SCORE = {
    "fastembed": [round(0.50 + 0.01 * i, 2) for i in range(31)],
    "hashing": [round(0.02 * i, 2) for i in range(31)],
}
GRID_Z = [0.0, *[round(1.5 + 0.25 * i, 2) for i in range(11)]]


class CachedEmbedder:
    """Memoises query vectors so threshold sweeps re-use one embedding per query."""

    def __init__(self, inner: Embedder) -> None:
        self.inner = inner
        self.name = inner.name
        self._cache: dict[str, list[float]] = {}

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.inner.embed_documents(texts)

    def embed_query(self, text: str) -> list[float]:
        if text not in self._cache:
            self._cache[text] = self.inner.embed_query(text)
        return self._cache[text]


def resolve_labels(queries: list[dict[str, Any]], books: list[dict[str, Any]]) -> dict[str, list[str]]:
    ids = {b["book_id"] for b in books}
    out: dict[str, list[str]] = {}
    for q in queries:
        if q.get("expect_empty"):
            out[q["id"]] = []
            continue
        rel = set(q.get("relevant_ids", []))
        unknown = rel - ids
        if unknown:
            raise SystemExit(f"{q['id']}: unknown book ids {sorted(unknown)}")
        subjects = {s.lower() for s in q.get("relevant_subjects", [])}
        rel |= {
            b["book_id"]
            for b in books
            if subjects & {s.lower() for s in [*b.get("subjects", []), b.get("discipline") or ""]}
        }
        if not rel:
            raise SystemExit(f"{q['id']}: label rule resolves to no book")
        out[q["id"]] = sorted(rel)
    return out


def score_query(q: dict[str, Any], prov: DemoLibraryProvider, rel: list[str], k: int) -> dict[str, Any]:
    t0 = time.perf_counter()
    found = prov.search(q["query"], limit=k)
    ms = (time.perf_counter() - t0) * 1000
    got = [b.book_id for b in found.books]
    row: dict[str, Any] = {
        "id": q["id"], "split": q["split"], "category": q["category"], "query": q["query"],
        "returned": got, "matched_on": found.matched_on, "relevant": rel, "search_ms": round(ms, 2),
    }  # fmt: skip
    if q.get("expect_empty"):
        row["correct_empty"] = not got
        return row
    relevant = set(rel)
    hits = [i for i, b in enumerate(got) if b in relevant]
    ideal = min(len(relevant), k)
    row["hit@k"] = bool(hits)
    row["recall@k"] = len(hits) / ideal
    row["precision@k"] = len(hits) / len(got) if got else 0.0
    row["mrr"] = 1 / (hits[0] + 1) if hits else 0.0
    dcg = sum(1 / math.log2(i + 2) for i in hits)
    row["ndcg@k"] = dcg / sum(1 / math.log2(i + 2) for i in range(ideal))
    row["empty"] = not got
    return row


def summarise(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pos = [r for r in rows if "hit@k" in r]
    neg = [r for r in rows if "correct_empty" in r]

    def mean(key: str, rs: list[dict[str, Any]]) -> float | None:
        return round(statistics.fmean(float(r[key]) for r in rs), 3) if rs else None

    ms = sorted(r["search_ms"] for r in rows)
    return {
        "queries": len(rows),
        "positives": len(pos),
        "negatives": len(neg),
        "hit@k": mean("hit@k", pos),
        "recall@k": mean("recall@k", pos),
        "precision@k": mean("precision@k", pos),
        "mrr": mean("mrr", pos),
        "ndcg@k": mean("ndcg@k", pos),
        "missed_rate": mean("empty", pos),
        "negatives_correct_empty": mean("correct_empty", neg),
        "objective": objective(rows),
        "search_p50_ms": round(statistics.median(ms), 2) if ms else None,
        "search_p95_ms": round(ms[min(len(ms) - 1, int(0.95 * len(ms)))], 2) if ms else None,
    }


def objective(rows: list[dict[str, Any]]) -> float:
    """Mean over queries: nDCG@k for topical queries, 1/0 for a correctly empty negative."""
    vals = [r["ndcg@k"] if "ndcg@k" in r else float(r["correct_empty"]) for r in rows]
    return round(statistics.fmean(vals), 4) if vals else 0.0


def run_mode(
    name: str, queries: list[dict[str, Any]], labels: dict[str, list[str]], args: argparse.Namespace
) -> dict[str, Any]:
    prov = DemoLibraryProvider()
    embedder_name = MODES[name]
    info: dict[str, Any] = {"mode": name, "status": "ok", "embedder": None, "gates": None, "tuning": None}
    if embedder_name:
        try:
            t0 = time.perf_counter()
            emb = CachedEmbedder(build_embedder(embedder_name))
            index = SemanticIndex.build(emb, prov.books, DEFAULT_MIN_SCORE[embedder_name], DEFAULT_MIN_Z[embedder_name])
            info["index_build_s"] = round(time.perf_counter() - t0, 2)
        except (EmbedderUnavailableError, OSError, ValueError) as exc:
            return {"mode": name, "status": "not_run", "reason": str(exc)[:300]}
        prov.enable_semantic(index)
        info["embedder"] = emb.name
        if args.tune:
            dev = [q for q in queries if q["split"] == "dev"]
            best: tuple[float, float, float] | None = None
            for z in GRID_Z:
                for s in GRID_SCORE[embedder_name]:
                    index.min_score, index.min_z = s, z
                    obj = objective([score_query(q, prov, labels[q["id"]], args.k) for q in dev])
                    # ties go to the stricter gates (fewer unrelated books shown)
                    if best is None or obj > best[0] or (obj == best[0] and (z, s) >= (best[2], best[1])):
                        best = (obj, s, z)
            assert best is not None
            index.min_score, index.min_z = best[1], best[2]
            info["tuning"] = {"split": "dev", "objective": best[0], "grid_min_score": GRID_SCORE[embedder_name],
                              "grid_min_z": GRID_Z}  # fmt: skip
        info["gates"] = {"min_score": index.min_score, "min_z": index.min_z}
        # How close the unrelated queries came to the absolute gate (best cosine among all books).
        ids = [bk["book_id"] for bk in prov.books]
        closest = {q["id"]: round(index.scores(q["query"], ids)[0][1], 4) for q in queries if q.get("expect_empty")}
        info["negatives_top_cosine"] = closest
        info["negative_margin"] = round(index.min_score - max(closest.values()), 4) if closest else None
    rows = [score_query(q, prov, labels[q["id"]], args.k) for q in queries]
    info["splits"] = {s: summarise([r for r in rows if r["split"] == s]) for s in ("dev", "test")}
    test = [r for r in rows if r["split"] == "test"]
    info["test_categories"] = {
        c: {k: v for k, v in summarise([r for r in test if r["category"] == c]).items()
            if k in ("queries", "hit@k", "recall@k", "precision@k", "ndcg@k", "negatives_correct_empty")}
        for c in sorted({r["category"] for r in test})
    }  # fmt: skip
    info["rows"] = rows
    return info


def to_markdown(report: dict[str, Any]) -> str:
    ok = [r for r in report["results"] if r["status"] == "ok"]
    k = report["k"]
    lines = [
        "# Library search benchmark (campus catalogue)",
        "",
        f"- Run: `{report['run_id']}` at {report['generated_at']}",
        f"- Dataset: `{report['dataset']}` ({report['dataset_sha256'][:12]}); catalogue "
        f"{report['catalogue']['books']} books ({report['catalogue']['sha256'][:12]}); k = {k}",
        f"- Gate tuning: {'on the dev split only' if report['tuned'] else 'none (configured gates)'}",
        "",
        f"Topical queries: Hit@{k} = a relevant book in the top {k}; Recall@{k} = share of relevant books found "
        f"(of at most {k}); Precision@{k} = share of returned books that are relevant; Missed = nothing returned.",
        "Negatives: the catalogue has no book on the topic, so the right answer is an empty result.",
        "",
    ]
    for split in ("test", "dev"):
        lines += [f"## {split} split", "",
                  f"| Mode | Hit@{k} | Recall@{k} | Precision@{k} | MRR | nDCG@{k} | Missed | Negatives empty | Objective | p50 / p95 ms |",
                  "|---|---|---|---|---|---|---|---|---|---|"]  # fmt: skip
        for r in ok:
            s = r["splits"][split]
            lines.append(
                f"| {r['mode']} | {s['hit@k']} | {s['recall@k']} | {s['precision@k']} | {s['mrr']} | {s['ndcg@k']} | "
                f"{s['missed_rate']} | {s['negatives_correct_empty']} | {s['objective']} | "
                f"{s['search_p50_ms']} / {s['search_p95_ms']} |"
            )
        if ok:
            s0 = ok[0]["splits"][split]
            lines += ["", f"Queries: {s0['queries']} ({s0['positives']} topical, {s0['negatives']} negatives).", ""]
    if ok:
        cats = sorted(ok[0]["test_categories"])
        lines += ["## Test split by category (Hit@k, or share of negatives correctly empty)", "",
                  "| Mode | " + " | ".join(cats) + " |", "|---|" + "---|" * len(cats)]  # fmt: skip
        for r in ok:
            tc = r["test_categories"]
            cells = [
                str(tc[c]["hit@k"] if tc[c]["hit@k"] is not None else tc[c]["negatives_correct_empty"]) for c in cats
            ]
            lines.append(f"| {r['mode']} | " + " | ".join(cells) + " |")
        lines.append("")
    lines += ["## Configuration", "", "| Mode | Embedder | Gates | Closest negative (cosine) | Index build |",
              "|---|---|---|---|---|"]  # fmt: skip
    for r in report["results"]:
        if r["status"] != "ok":
            lines.append(f"| {r['mode']} | **not run**: {r['reason']} | | | |")
            continue
        g = r["gates"]
        gates = f"min_score={g['min_score']}, min_z={g['min_z']}" if g else "keyword tiers only"
        build = f"{r['index_build_s']} s" if "index_build_s" in r else "-"
        near = r.get("negatives_top_cosine") or {}
        worst = max(near, key=near.__getitem__) if near else None
        margin = f"{near[worst]} ({worst}; {r['negative_margin']} below min_score)" if worst else "-"
        lines.append(f"| {r['mode']} | `{r['embedder'] or '-'}` | {gates} | {margin} | {build} |")
    lines += [
        "",
        "hybrid-hashing uses a lexical hashing embedder (an offline baseline, not semantic). FastEmbed index build",
        "includes model load. Small samples (one query per topic) mean differences of one or two queries matter.",
        "A small negative margin means an unrelated query came close to the gate: treat negatives as fragile.",
        "",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--modes", default=",".join(MODES), help=f"Comma list from {list(MODES)}")
    parser.add_argument("--dataset", default=str(DATASET))
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--tune", action="store_true", help="Tune semantic gates on dev, then score test")
    parser.add_argument("--query", action="append", help="Only these query ids (debugging; no report written)")
    parser.add_argument("--out", default=str(REPORTS))
    args = parser.parse_args()
    names = [n.strip() for n in args.modes.split(",") if n.strip()]
    if set(names) - set(MODES):
        parser.error(f"unknown mode(s): {sorted(set(names) - set(MODES))}")
    raw = Path(args.dataset).read_bytes()
    queries = yaml.safe_load(raw)["queries"]
    books = DemoLibraryProvider().books
    labels = resolve_labels(queries, books)
    if args.query:
        queries = [q for q in queries if q["id"] in set(args.query)]
    results = []
    for name in names:
        print(f"== {name}", file=sys.stderr)
        res = run_mode(name, queries, labels, args)
        results.append(res)
        if res["status"] == "ok" and not args.query:
            t = res["splits"]["test"]
            print(f"   test hit@{args.k}={t['hit@k']} P={t['precision@k']} negEmpty={t['negatives_correct_empty']} "
                  f"gates={res['gates']}", file=sys.stderr)  # fmt: skip
        elif res["status"] != "ok":
            print(f"   NOT RUN: {res['reason']}", file=sys.stderr)
    if args.query:
        for r in results:
            for row in r.get("rows", []):
                print(r["mode"], json.dumps(row))
        return
    generated = datetime.now(UTC)
    cat_bytes = DEMO_DATA_PATH.read_bytes()
    report = {
        "kind": "library_search",
        "run_id": f"library-{generated.strftime('%Y%m%dT%H%M%SZ')}-{hashlib.sha256(raw).hexdigest()[:6]}",
        "generated_at": generated.isoformat(timespec="seconds"),
        "dataset": Path(args.dataset).name,
        "dataset_sha256": hashlib.sha256(raw).hexdigest(),
        "catalogue": {"books": len(books), "sha256": hashlib.sha256(cat_bytes).hexdigest()},
        "k": args.k,
        "tuned": args.tune,
        "labels": labels,
        "results": results,
    }
    out = Path(args.out)
    (out / "runs").mkdir(parents=True, exist_ok=True)
    (out / "runs" / f"{report['run_id']}.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    (out / "library-latest.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    (out / "library-latest.md").write_text(to_markdown(report), encoding="utf-8")
    print(f"wrote runs/{report['run_id']}.json and library-latest.{{json,md}}", file=sys.stderr)


if __name__ == "__main__":
    main()
