# `08-contract-review/evals/`: golden set and scores

Offline evaluation data for this project. The portfolio runner (`python -m evals`, see
[`/evals`](../../../evals/README.md)) feeds every case in `golden.jsonl` to the project's
`run_case` function, aggregates the metrics with [`shared/evals`](../../../shared/evals/README.md)
and gates on the thresholds declared in `doctrine.yaml`.

| File | What it does |
|---|---|
| [`golden.jsonl`](golden.jsonl) | Golden set: 12 cases, one JSON object per line with `id`, `input` and `expect`. Examples: `EV1-demo-msa`, `EV2-balanced`, `EV3-evergreen`, `EV4-supplier`, ... |
| [`run_eval.py`](run_eval.py) | Precision/recall gate over the same golden file: `python projects/08-contract-review/evals/run_eval.py --min-precision 0.8 --min-recall 0.8`. Exits non-zero below the thresholds; CI runs it. |
| [`scores.json`](scores.json) | Latest metrics, thresholds and pass/fail written by `python -m evals`. Read by `python -m shared.doctrine` to render `DOCTRINE.md` and the root README matrix; do not edit by hand. |

## Gate

Thresholds come from [`../doctrine.yaml`](../doctrine.yaml) (`eval.thresholds`). Current values
are from the checked-in `scores.json`:

| Metric | Threshold | Current |
|---|---|---|
| Task success | `>=0.7` | 0.75 |
| Groundedness | `>=0.95` | 1.00 |
| Policy violation rate | `<=0` | 0.00 |

A `cost_per_task` ceiling is also enforced; it is computed from the mock model's token estimates, so treat it as a regression signal rather than a real cost.

## Run

```bash
python -m evals --project 08             # run the cases, refresh scores.json
python -m evals --project 08 --no-write  # gate only (what CI does)
python -m evals --project 08 -v          # list failing cases
```

Each case is executed by `contract_review.eval_suite:run_case` in [`contract_review/eval_suite.py`](../contract_review/eval_suite.py).

## Why task success is 0.75

Three golden cases are known misses on purpose: an evergreen renewal phrased without
"automatically renew", a standard indirect-damages exclusion that a naive rule flags, and an
over-rated severity. The threshold (`>=0.7`) reflects that, so the numbers stay realistic.
`run_eval.py` reports the complementary precision/recall view of flagged risks.
