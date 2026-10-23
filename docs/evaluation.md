# Evaluation

Dataset: `evals/datasets/campus_eval_v1.yaml`, with 51 cases in 9 categories (single server 14, academic RAG 10, multi-server 6, no supporting data 5, unnecessary tool calls 4, simulated failure 4, ambiguous 3, malformed input 3, prompt injection 2). Each case states the exact set of servers that *should* be called, the facts the answer must and must not contain, the expected citation (file and page), and any injected faults.

## Metrics (computed by `evals/run_eval.py`)
- **Tool-selection accuracy**: the set of servers called equals the expected set (or one listed alternative).
- **Answer correctness**: every `must_contain` string is present and no `must_not_contain` string is.
- **Citation correctness**: a returned citation matches the expected file and page **and** every page reference in the answer verifies against retrieved passages; for `expect_insufficient` cases, no citation and `insufficient_evidence=true`.
- **Unnecessary tool-call rate**: calls to servers outside the expected set, divided by all calls.
- **Failure recovery**: on fault cases, the expected status (`partial`) is reached, the answer is still correct, and every non-faulted call succeeded.
- **Latency**: end-to-end per case (p50/p95/mean) and per tool call (p50/p95), excluding run-cache hits.

## Modes
| Command | LLM | MCP transport | Report |
|---|---|---|---|
| `python -m evals.run_eval` | mock | in-process `MCPServer` via SDK `Client` (fixed clock 2026-10-23) | `reports/latest.*` |
| `python -m evals.run_eval --transport http` | mock | running server processes on :8101–8104 (real clock) | `reports/latest-http.*` |
| `python -m evals.run_eval --provider groq --delay 3` | GroqCloud `openai/gpt-oss-120b` | in-process | `reports/latest-groq.*` |

Live runs make roughly 2–4 Groq requests per case. On the free tier (30 RPM, 8K TPM for this model), use `--delay` and expect some `llm_rate_limited` cases; they show up as failures in the report rather than being retried silently.

## Interpreting the mock results
The mock provider's planner is a keyword router written alongside this dataset, so its tool-selection score is close to tautological: it shows that discovery, routing, validation and execution work, **not** that an LLM would choose correctly. The parts that do carry signal under mock are the real MCP servers, retrieval, chunking, citation verification, failure handling and latency. The same dataset run against Groq measures the model.

Current known failure: `rag-07` ("Can I use ChatGPT for my assignments?"). The handbook says "generative AI tools", and the lexical hashing embedder can't bridge that paraphrase. It should pass with `EMBEDDING_PROVIDER=fastembed`; that has not been measured here.

## Changes made because of evaluation (first run 42/51, then 50/51)
1. Chunks were up to 700 characters across several clauses, burying facts like the re-evaluation fee. Chunking now follows clauses and Q&A pairs, which raised the corpus from 14 to 32 chunks.
2. Library search matched stopwords ("Lord **of the** Rings" → *The Pragmatic Programmer*). It now drops stopwords and requires a majority of terms to match.
3. A passage made entirely of injected instructions was returned as evidence. It is now withheld, with a message.
4. The mock synthesiser truncated excerpts and split sentences after "Rs."; it now quotes the best-matching sentences.
5. One malformed-input expectation ("no tool call" for an SQL-ish string) was relaxed to accept a validated read-only search, because that is harmless. This is the only expectation that was changed.
