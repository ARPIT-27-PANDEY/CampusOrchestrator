# Library search benchmark (campus catalogue)

- Run: `library-20261029T092812Z-49c546` at 2026-10-29T09:28:12+00:00
- Dataset: `library_search_v1.yaml` (49c546a52ee4); catalogue 138 books (2115945542ef); k = 5
- Gate tuning: on the dev split only

Topical queries: Hit@5 = a relevant book in the top 5; Recall@5 = share of relevant books found (of at most 5); Precision@5 = share of returned books that are relevant; Missed = nothing returned.
Negatives: the catalogue has no book on the topic, so the right answer is an empty result.

## test split

| Mode | Hit@5 | Recall@5 | Precision@5 | MRR | nDCG@5 | Missed | Negatives empty | Objective | p50 / p95 ms |
|---|---|---|---|---|---|---|---|---|---|
| keyword | 0.44 | 0.44 | 0.42 | 0.44 | 0.44 | 0.56 | 1.0 | 0.5484 | 3.51 / 5.9 |
| hybrid-hashing | 0.44 | 0.44 | 0.42 | 0.44 | 0.44 | 0.56 | 1.0 | 0.5484 | 8.06 / 12.77 |
| hybrid-fastembed | 0.92 | 0.787 | 0.781 | 0.888 | 0.794 | 0.0 | 1.0 | 0.8335 | 14.75 / 18.98 |

Queries: 31 (25 topical, 6 negatives).

## dev split

| Mode | Hit@5 | Recall@5 | Precision@5 | MRR | nDCG@5 | Missed | Negatives empty | Objective | p50 / p95 ms |
|---|---|---|---|---|---|---|---|---|---|
| keyword | 0.48 | 0.433 | 0.403 | 0.448 | 0.432 | 0.52 | 1.0 | 0.5418 | 3.64 / 5.04 |
| hybrid-hashing | 0.48 | 0.433 | 0.403 | 0.448 | 0.432 | 0.52 | 1.0 | 0.5418 | 9.19 / 14.95 |
| hybrid-fastembed | 0.96 | 0.861 | 0.719 | 0.9 | 0.844 | 0.04 | 1.0 | 0.8743 | 7.71 / 19.61 |

Queries: 31 (25 topical, 6 negatives).

## Test split by category (Hit@k, or share of negatives correctly empty)

| Mode | alias | author | negative | paraphrase | subject | title |
|---|---|---|---|---|---|---|
| keyword | 1.0 | 1.0 | 1.0 | 0.0 | 1.0 | 1.0 |
| hybrid-hashing | 1.0 | 1.0 | 1.0 | 0.0 | 1.0 | 1.0 |
| hybrid-fastembed | 1.0 | 1.0 | 1.0 | 0.857 | 1.0 | 1.0 |

## Configuration

| Mode | Embedder | Gates | Closest negative (cosine) | Index build |
|---|---|---|---|---|
| keyword | `-` | keyword tiers only | - | - |
| hybrid-hashing | `hashing-v1-512` | min_score=0.6, min_z=4.0 | 0.3095 (n09; 0.2905 below min_score) | 0.02 s |
| hybrid-fastembed | `fastembed:BAAI/bge-small-en-v1.5` | min_score=0.68, min_z=1.5 | 0.673 (n03; 0.007 below min_score) | 5.95 s |

hybrid-hashing uses a lexical hashing embedder (an offline baseline, not semantic). FastEmbed index build
includes model load. Small samples (one query per topic) mean differences of one or two queries matter.
A small negative margin means an unrelated query came close to the gate: treat negatives as fragile.

