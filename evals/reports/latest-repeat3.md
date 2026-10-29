# CampusOrchestrator evaluation report

- Run: `agent-20261028T215803Z-mock-551ee3` (2026-10-28T21:58:03+00:00)
- Dataset: `campus_eval_v2.yaml` v2 (66 cases x 3), fixtures v2
- Provider / model: mock / `mock-deterministic-v1`; transport: inprocess; retriever: hashing
- Prompt 08bee2bd11bc, tool schemas 50f7ce4c0abc, commit 06f2fce1f7 (uncommitted changes)

> Mock-provider run: tool choice comes from a deterministic keyword router, so tool-selection numbers measure the pipeline (MCP discovery, routing, validation, retrieval, citations, failure handling), not GPT-OSS-120B's judgement. Run with --provider groq for a live-model evaluation.

| Metric | Value |
|---|---|
| Cases passed | 186/198 (93.9%) |
| Tool-selection accuracy (exact tool set) | 100.0% |
| Server-selection accuracy | 100.0% |
| Argument accuracy (30 cases) | 100.0% |
| Answer correctness (required facts present, forbidden absent) | 95.5% |
| Citation / abstention correctness (30 cases) | 90.0% |
| Source-mode labelling | 100.0% |
| Unnecessary / repeated tool-call rate (234 calls) | 0.0% / 5.1% |
| Recovery from injected MCP faults (21 cases) | 100.0% |
| Tool budget exhausted | 3 |
| Mean LLM turns | 2.06 |
| Results with status=error / model infrastructure errors | 9 / 0 |
| Latency p50 / p95 / p99 (n=189, non-error) | 57.6 / 397.2 / 4303.2 ms |
| First token p50 (n=189) | 57.5 ms |
| LLM wall p50 / tool wall p50 / discovery p50 | 0.8 / 44.4 / 8.9 ms |
| Tokens (prompt / completion) | 0 / 0 |

_Latency percentiles use requests that did not end in status=error; error and fault counts are reported separately. In-process transport has no network hop; the first case includes cold-start costs (no warm-up). p99 is reported only with at least 100 samples._

## By category

| Category | Passed |
|---|---|
| single_server | 30/30 |
| topic_search | 9/9 |
| no_results | 6/6 |
| date_boundary | 6/6 |
| paraphrase | 3/3 |
| public_books | 12/12 |
| public_books_partial | 3/3 |
| date_relative | 12/12 |
| filters | 6/6 |
| official_calendar | 6/6 |
| status | 3/3 |
| academic_rag | 9/18 |
| superseded_policy | 3/3 |
| applicability | 3/3 |
| insufficient_evidence | 3/6 |
| multi_server | 15/15 |
| no_tool | 3/3 |
| ambiguous | 6/6 |
| out_of_scope | 3/3 |
| failure | 21/21 |
| llm_failure | 12/12 |
| tool_budget | 3/3 |
| injection | 6/6 |
| extensibility | 3/3 |

## Failed cases

- **acad-03** (academic_rag, reasoning): How many credits can I register for in a semester?
  - answer missing '24 credits'
- **acad-06** (academic_rag, reasoning): How many credits can a UG student transfer through the Academic Bank of Credits?
  - answer missing '20 credits'
- **acad-09** (insufficient_evidence, reasoning): What is the policy on using ChatGPT for assignments?
  - expected an insufficient-evidence result
- **acad-10** (academic_rag, reasoning): What is the maximum duration of a B.Tech programme?
  - answer contains none of ['six years', '6 years']
- **acad-03** (academic_rag, reasoning): How many credits can I register for in a semester?
  - answer missing '24 credits'
- **acad-06** (academic_rag, reasoning): How many credits can a UG student transfer through the Academic Bank of Credits?
  - answer missing '20 credits'
- **acad-09** (insufficient_evidence, reasoning): What is the policy on using ChatGPT for assignments?
  - expected an insufficient-evidence result
- **acad-10** (academic_rag, reasoning): What is the maximum duration of a B.Tech programme?
  - answer contains none of ['six years', '6 years']
- **acad-03** (academic_rag, reasoning): How many credits can I register for in a semester?
  - answer missing '24 credits'
- **acad-06** (academic_rag, reasoning): How many credits can a UG student transfer through the Academic Bank of Credits?
  - answer missing '20 credits'
- **acad-09** (insufficient_evidence, reasoning): What is the policy on using ChatGPT for assignments?
  - expected an insufficient-evidence result
- **acad-10** (academic_rag, reasoning): What is the maximum duration of a B.Tech programme?
  - answer contains none of ['six years', '6 years']
