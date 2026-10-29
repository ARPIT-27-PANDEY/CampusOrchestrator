# CampusOrchestrator evaluation report

- Run: `agent-20261028T215615Z-mock-0360e9` (2026-10-28T21:56:15+00:00)
- Dataset: `campus_eval_v1.yaml` v1 (51 cases x 1), fixtures v1
- Provider / model: mock / `mock-deterministic-v1`; transport: inprocess; retriever: hashing (v1 demo handbook)
- Prompt 08bee2bd11bc, tool schemas 5a664ea395ba, commit 06f2fce1f7 (uncommitted changes)

> Mock-provider run: tool choice comes from a deterministic keyword router, so tool-selection numbers measure the pipeline (MCP discovery, routing, validation, retrieval, citations, failure handling), not GPT-OSS-120B's judgement. Run with --provider groq for a live-model evaluation.

| Metric | Value |
|---|---|
| Cases passed | 50/51 (98.0%) |
| Tool-selection accuracy (exact tool set) | 100.0% |
| Server-selection accuracy | 100.0% |
| Argument accuracy (0 cases) | n/a |
| Answer correctness (required facts present, forbidden absent) | 98.0% |
| Citation / abstention correctness (17 cases) | 94.1% |
| Source-mode labelling | n/a |
| Unnecessary / repeated tool-call rate (60 calls) | 0.0% / 0.0% |
| Recovery from injected MCP faults (4 cases) | 100.0% |
| Tool budget exhausted | 0 |
| Mean LLM turns | 1.94 |
| Results with status=error / model infrastructure errors | 0 / 0 |
| Latency p50 / p95 / p99 (n=51, non-error) | 42.4 / 312.2 / n/a ms |
| First token p50 (n=51) | 42.3 ms |
| LLM wall p50 / tool wall p50 / discovery p50 | 0.9 / 32.9 / 8.8 ms |
| Tokens (prompt / completion) | 0 / 0 |

_Latency percentiles use requests that did not end in status=error; error and fault counts are reported separately. In-process transport has no network hop; the first case includes cold-start costs (no warm-up). p99 is reported only with at least 100 samples._

## By category

| Category | Passed |
|---|---|
| single_server | 14/14 |
| multi_server | 6/6 |
| academic_rag | 9/10 |
| no_supporting_data | 5/5 |
| unnecessary_tool_calls | 4/4 |
| ambiguous | 3/3 |
| simulated_failure | 4/4 |
| malformed_input | 3/3 |
| prompt_injection | 2/2 |

## Failed cases

- **rag-07** (academic_rag, reasoning): Can I use ChatGPT for my assignments?
  - answer missing 'generative AI'
  - citation: expected one of ['academic_handbook_2026.pdf:p5'], got ['none']
  - note: Paraphrase test: 'ChatGPT' never appears in the handbook. Expected to fail with the lexical hashing embedder.
