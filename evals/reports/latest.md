# CampusOrchestrator evaluation report

- Run: `agent-20261028T215646Z-mock-b538b9` (2026-10-28T21:56:46+00:00)
- Dataset: `campus_eval_v2.yaml` v2 (66 cases x 1), fixtures v2
- Provider / model: mock / `mock-deterministic-v1`; transport: inprocess; retriever: hashing
- Prompt 08bee2bd11bc, tool schemas 50f7ce4c0abc, commit 06f2fce1f7 (uncommitted changes)

> Mock-provider run: tool choice comes from a deterministic keyword router, so tool-selection numbers measure the pipeline (MCP discovery, routing, validation, retrieval, citations, failure handling), not GPT-OSS-120B's judgement. Run with --provider groq for a live-model evaluation.

| Metric | Value |
|---|---|
| Cases passed | 62/66 (93.9%) |
| Tool-selection accuracy (exact tool set) | 100.0% |
| Server-selection accuracy | 100.0% |
| Argument accuracy (10 cases) | 100.0% |
| Answer correctness (required facts present, forbidden absent) | 95.5% |
| Citation / abstention correctness (10 cases) | 90.0% |
| Source-mode labelling | 100.0% |
| Unnecessary / repeated tool-call rate (78 calls) | 0.0% / 5.1% |
| Recovery from injected MCP faults (7 cases) | 100.0% |
| Tool budget exhausted | 1 |
| Mean LLM turns | 2.06 |
| Results with status=error / model infrastructure errors | 3 / 0 |
| Latency p50 / p95 / p99 (n=63, non-error) | 49.3 / 312.1 / n/a ms |
| First token p50 (n=63) | 49.2 ms |
| LLM wall p50 / tool wall p50 / discovery p50 | 0.8 / 36.4 / 9.8 ms |
| Tokens (prompt / completion) | 0 / 0 |

_Latency percentiles use requests that did not end in status=error; error and fault counts are reported separately. In-process transport has no network hop; the first case includes cold-start costs (no warm-up). p99 is reported only with at least 100 samples._

## By category

| Category | Passed |
|---|---|
| single_server | 10/10 |
| topic_search | 3/3 |
| no_results | 2/2 |
| date_boundary | 2/2 |
| paraphrase | 1/1 |
| public_books | 4/4 |
| public_books_partial | 1/1 |
| date_relative | 4/4 |
| filters | 2/2 |
| official_calendar | 2/2 |
| status | 1/1 |
| academic_rag | 3/6 |
| superseded_policy | 1/1 |
| applicability | 1/1 |
| insufficient_evidence | 1/2 |
| multi_server | 5/5 |
| no_tool | 1/1 |
| ambiguous | 2/2 |
| out_of_scope | 1/1 |
| failure | 7/7 |
| llm_failure | 4/4 |
| tool_budget | 1/1 |
| injection | 2/2 |
| extensibility | 1/1 |

## Failed cases

- **acad-03** (academic_rag, reasoning): How many credits can I register for in a semester?
  - answer missing '24 credits'
- **acad-06** (academic_rag, reasoning): How many credits can a UG student transfer through the Academic Bank of Credits?
  - answer missing '20 credits'
- **acad-09** (insufficient_evidence, reasoning): What is the policy on using ChatGPT for assignments?
  - expected an insufficient-evidence result
- **acad-10** (academic_rag, reasoning): What is the maximum duration of a B.Tech programme?
  - answer contains none of ['six years', '6 years']
