# CampusOS evaluation report

- Generated: 2026-10-23T15:21:31+00:00
- Dataset: `campus_eval_v1.yaml` (51 cases)
- Provider / model: mock / `mock-deterministic-v1`; MCP transport: inprocess

> Mock-provider run: tool choice comes from a deterministic keyword router, so tool-selection numbers measure the pipeline (MCP discovery, routing, validation, retrieval, citations, failure handling), not GPT-OSS-120B's judgement. Run with --provider groq for a live-model evaluation.

| Metric | Value |
|---|---|
| Cases passed | 50/51 (98.0%) |
| Tool-selection accuracy (exact server set) | 100.0% |
| Answer correctness (required facts present, forbidden absent) | 98.0% |
| Citation correctness (17 cases) | 94.1% |
| Unnecessary tool-call rate (60 calls) | 0.0% |
| Recovery from simulated failures (4 cases) | 100.0% |
| End-to-end latency p50 / p95 | 22.9 ms / 275.3 ms |
| Tool-call duration p50 / p95 | 13.8 ms / 22.4 ms |

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

- **rag-07** (academic_rag): Can I use ChatGPT for my assignments?
  - answer missing 'generative AI'
  - citation: expected academic_handbook_2026.pdf:p5, got none
  - note: Paraphrase test: 'ChatGPT' never appears in the handbook. Expected to fail with the lexical hashing embedder.
