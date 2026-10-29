# Retrieval benchmark (official IIT Roorkee corpus)

- Run: `retrieval-20261028T221029Z-b025a8` at 2026-10-28T22:10:29+00:00
- Dataset: `retrieval_iitr_v1.yaml` (b025a88d9830), k = 5
- Corpus: 17 official PDFs + 1 benchmark-only injection notice; manifest lock 45d93d994f7f
- Threshold tuning: on the dev split only

Recall@k = share of labelled passages found in the top k; MRR uses the first relevant hit; nDCG@5 uses
graded labels (2 = answers, 1 = related). Abstention: the service reports no supporting evidence.

## test split

| Retriever | R@1 | R@3 | R@5 | MRR | nDCG@5 | Abstain P | Abstain R | False abstain | Top cite ok | Current doc first | Injection sanitised | Search p50/p95 ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| hashing | 0.314 | 0.4767 | 0.5233 | 0.4388 | 0.4513 | 0.2727 | 1.0 | 0.3721 | 0.5926 (27) | 0/1 | 1/1 | 17.21 / 43.12 |
| fastembed | 0.5659 | 0.8178 | 0.8527 | 0.774 | 0.7781 | 0.5 | 1.0 | 0.1395 | 0.6757 (37) | 1/1 | 1/1 | 36.95 / 53.92 |
| hybrid | 0.438 | 0.6008 | 0.6705 | 0.595 | 0.6 | 0.3 | 1.0 | 0.3256 | 0.7586 (29) | 1/1 | 1/1 | 20.4 / 40.84 |
| hybrid-fastembed | 0.5659 | 0.8023 | 0.8605 | 0.7585 | 0.766 | 0.5 | 1.0 | 0.1395 | 0.7027 (37) | 1/1 | 1/1 | 36.11 / 55.56 |

Queries: 49 (6 without supporting documents).

## dev split

| Retriever | R@1 | R@3 | R@5 | MRR | nDCG@5 | Abstain P | Abstain R | False abstain | Top cite ok | Current doc first | Injection sanitised | Search p50/p95 ms |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| hashing | 0.3611 | 0.5278 | 0.6111 | 0.5463 | 0.5423 | 0.8 | 1.0 | 0.0556 | 0.4118 (17) | 1/1 | None | 20.56 / 43.78 |
| fastembed | 0.7778 | 0.9167 | 0.9722 | 0.9722 | 0.9555 | 1.0 | 1.0 | 0.0 | 0.9444 (18) | 1/1 | None | 39.79 / 67.88 |
| hybrid | 0.4444 | 0.6389 | 0.7222 | 0.6481 | 0.6417 | 1.0 | 1.0 | 0.0 | 0.5 (18) | 1/1 | None | 28.62 / 50.68 |
| hybrid-fastembed | 0.6667 | 0.8056 | 0.9722 | 0.8889 | 0.896 | 1.0 | 1.0 | 0.0 | 0.8333 (18) | 1/1 | None | 42.29 / 73.88 |

Queries: 22 (4 without supporting documents).

## Configuration

| Retriever | Embedding | Dim | Mode | Thresholds | Index build | Python heap peak |
|---|---|---|---|---|---|---|
| hashing | `hashing-v1-512` | 512 | dense | min_score=0.2 | 4.88 s | 11.2 MB |
| fastembed | `fastembed:BAAI/bge-small-en-v1.5` | 384 | dense | min_score=0.72 | 86.7 s | 9.3 MB |
| hybrid | `hashing-v1-512` | 512 | hybrid | min_score=0.2, bm25_min=15.0 | 4.52 s | 11.1 MB |
| hybrid-fastembed | `fastembed:BAAI/bge-small-en-v1.5` | 384 | hybrid | min_score=0.72, bm25_min=off | 86.49 s | 9.3 MB |

Index build for FastEmbed includes model load (the first run also downloads ~130 MB of ONNX weights).
No-answer samples are small (dev 4, test 6), so abstention rates have wide uncertainty.

Python heap peak is measured with tracemalloc and excludes native (ONNX runtime) memory.

