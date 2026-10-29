# Evaluation run artifacts

Every evaluation run writes one immutable JSON file here (`agent-*` from `python -m evals.run_eval`,
`retrieval-*` from `python -m evals.run_retrieval`). Files are never rewritten; the `latest*.json/md`
files one level up are convenience copies of the most recent full run of each kind.

Compare two runs: `python -m evals.compare <run_a> <run_b>`; list runs: `python -m evals.compare --list`.

## Legacy artifacts

`agent-legacy-v1-*.json/md` are the reports that were committed before run history existed
(`evals/reports/latest*.json` at commit 06f2fce), preserved unchanged.

## Known-invalid runs (kept for the record)

| Run | Problem | Superseded by |
|---|---|---|
| `retrieval-20261028T210734Z-b025a8` | nDCG@5 counted a label once per matching chunk (values > 1 possible); hybrid tuning swept only the BM25 threshold while the dense gate stayed at a permissive default, so hybrid never abstained. Both fixed in `evals/run_retrieval.py`. | `retrieval-20261028T212446Z-b025a8` |
