# Evaluation

Two benchmarks, both producing immutable run files in `evals/reports/runs/` (never overwritten) plus
`latest*` convenience copies. Every number is measured by the scripts; nothing is hand-entered.

## 1. Agent benchmark - `python -m evals.run_eval`

| Dataset | Cases | Fixtures | Notes |
|---|---:|---|---|
| `campus_eval_v1.yaml` | 51 | v1 (fictional handbook, original demo data) | Kept unchanged and runnable |
| `campus_eval_v2.yaml` | 66 | v2 (official IITR corpus, expanded demo data, recorded public-book API responses, test-only Transport server) | Default |

v2 categories: single-service, topic search, public books (incl. a recorded provider outage), filters,
relative dates and midnight boundaries, official calendar, event status, academic RAG, superseded policy,
applicability, insufficient evidence, multi-service, no-tool/ambiguous/out-of-scope, MCP failures
(down at discovery, down mid-run, timeout, flaky, malformed response, one of several services failing),
model failures (rate limit, timeout, malformed tool call, unknown tool, endless tool loop), injection and
dynamic discovery of an unknown server. The clock is fixed (Thursday 2026-10-29 10:00 IST).

Each case states expected behaviour, not just a phrase: `expected_tools` (+ `acceptable_tools`),
`expected_args`, `must_contain` / `must_contain_any` / `must_not_contain`, `expect_status`,
`expect_source_modes`, `expected_citation_any`, `expect_insufficient`, `faults`, `llm_fault`,
`extra_servers`.

### Metrics

| Metric | Definition |
|---|---|
| Tool-selection accuracy | the set of tools called equals an expected set exactly |
| Service-selection accuracy | the set of services called equals the expected set |
| Argument accuracy | expected argument values (dates, filters) were passed (cases with `expected_args`) |
| Answer correctness | required facts present and forbidden claims absent |
| Citation / abstention | a returned citation matches an expected document page, or the system abstained when it should |
| Source-mode labelling | sources report the expected `demo`/`imported`/`live` mode |
| Unnecessary / repeated calls | calls outside the expected set; identical calls repeated in one run |
| Recovery | with injected MCP faults: status as expected, answer correct, every healthy service succeeded |
| Failure class | `reasoning` (wrong tools/answer), `fault_handling` (our handling of injected faults), `infra_llm` (provider 429/timeout/auth, reported separately from reasoning) |

**MockProvider is not a language model.** It is a deterministic keyword router (with a generic fallback
that picks a discovered tool by its name/description). Its tool-selection score shows the pipeline works;
it says nothing about GPT-OSS-120B. Mock and live runs are never presented as equivalent models.

### Options

```bash
python -m evals.run_eval                                   # v2, mock, in-process MCP servers
python -m evals.run_eval --dataset evals/datasets/campus_eval_v1.yaml
python -m evals.run_eval --transport http                  # against running MCP server processes
python -m evals.run_eval --retriever fastembed             # academics retrieval: hashing|hybrid|fastembed|hybrid-fastembed
python -m evals.run_eval --repeat 3                        # repeated runs; reports unstable cases
python -m evals.run_eval --category failure --category llm_failure   # fault-injection benchmark
python -m evals.run_eval --case acad-04 --case evt2-01     # targeted debugging (no latest pointer)
python -m evals.run_eval --provider groq --case acad-01    # LIVE: <= 5 cases without confirmation
python -m evals.run_eval --provider groq --yes-live --delay 3        # LIVE full run: prints the expected request count first
```

Live runs need `GROQ_API_KEY`, print the number of cases and an estimate of Groq requests, and refuse
more than 5 cases without `--yes-live`. Cases with `llm_fault` are skipped on live runs (they measure our
handling, not the model). CI never uses Groq.

Each run records provider, model and settings, prompt version (hash), tool-schema hash, dataset version
and sha256, fixtures version, retriever, transport, repeat count, timezone and clock, git commit (and
whether the tree was dirty), Python version and platform.

## 2. Retrieval benchmark - `python -m evals.run_retrieval`

`evals/datasets/retrieval_iitr_v1.yaml`: 71 questions over the official corpus (21 dev / 50 test; 10
without a supporting document; exact terms, paraphrases, synonyms, numbers, multi-passage, short/long,
superseded, applicability, misleading terminology, and one prompt-injection case against a
benchmark-only synthetic notice). Labels are `{doc, page, evidence, grade}` written against the PDFs;
the runner checks every label resolves to an indexed chunk and records the chunk ids.

Retrievers (same documents, chunking, labels and queries):

| Name | Embedding | Retrieval |
|---|---|---|
| `hashing` | `hashing-v1-512` (lexical, offline) | dense cosine |
| `fastembed` | `BAAI/bge-small-en-v1.5` (384-d, ONNX) | dense cosine |
| `hybrid` | hashing + in-memory BM25 | Reciprocal Rank Fusion (k = 60) |
| `hybrid-fastembed` | fastembed + BM25 | RRF |

Each embedding space has its own Qdrant collection (`<collection>__<embedder>`), so vectors are never
mixed; the hashing baseline stays reproducible.

Metrics: Recall@1/3/5 (share of labelled passages in the top k), MRR, nDCG@5 (graded, each label counted
once), abstention precision/recall, false-abstention rate, top-citation support, current-document-first
for superseded cases, injection sanitisation, retrieval/search latency p50/p95, index build time and
Python heap peak (tracemalloc; excludes native ONNX memory).

`--tune` chooses the relevance threshold(s) on the **dev** split only (balanced accuracy of
answer-vs-abstain) and applies them unchanged to **test**. For hybrid both the dense and the BM25
thresholds are swept jointly.

```bash
python -m evals.run_retrieval --retrievers hashing,hybrid --tune            # offline, used in CI
pip install "campusos-academics-mcp[fastembed]"                              # optional; downloads ~130 MB on first use
python -m evals.run_retrieval --retrievers hashing,fastembed,hybrid,hybrid-fastembed --tune
```

A retriever that cannot run (e.g. FastEmbed not installed) is reported as `not_run` with the reason -
never filled with another retriever's numbers.

## Latency

End-to-end latency is the server-side wall time of a run (`time.perf_counter()`). Each run also records
discovery time, every LLM call's duration (LLM wall), time to first streamed token, tool wall time
versus the sum of individual tool durations (they differ when calls run concurrently), retries and cache
hits. Reports give p50/p95 (p99 only with at least 100 samples), the mean, the sample size, and count
error results separately; percentiles use non-error runs only. In-process transport has no network hop;
the first case includes cold-start costs (no warm-up). Mock latencies contain no model inference.

## Comparing runs

```bash
python -m evals.compare --list
python -m evals.compare <run_a> <run_b>        # metric deltas, regressions, improvements
```

The Evaluation page shows the same: pick a run, optionally compare with another; it warns when datasets
differ or when a mock run is compared with a live one.

## Results

See [`evals/reports/latest.md`](../evals/reports/latest.md), `latest-v1.md`, `latest-fastembed.md`,
`latest-repeat3.md` and [`evals/reports/retrieval-latest.md`](../evals/reports/retrieval-latest.md).
The README summarises them. No live Groq evaluation is included in this repository's reports.
