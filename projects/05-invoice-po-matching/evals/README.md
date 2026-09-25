# `05-invoice-po-matching/evals/`: golden set and scores

Offline evaluation data for this project. The portfolio runner (`python -m evals`, see
[`/evals`](../../../evals/README.md)) feeds every case in `golden.jsonl` to the project's
`run_case` function, aggregates the metrics with [`shared/evals`](../../../shared/evals/README.md)
and gates on the thresholds declared in `doctrine.yaml`.

| File | What it does |
|---|---|
| [`golden.jsonl`](golden.jsonl) | Golden set: 12 cases, one JSON object per line with `id`, `input` and `expect`. Examples: `clean-approved`, `variance-three-codes`, `po-not-found`, `po-closed`, ... |
| [`scores.json`](scores.json) | Latest metrics, thresholds and pass/fail written by `python -m evals`. Read by `python -m shared.doctrine` to render `DOCTRINE.md` and the root README matrix; do not edit by hand. |

## Gate

Thresholds come from [`../doctrine.yaml`](../doctrine.yaml) (`eval.thresholds`). Current values
are from the checked-in `scores.json`:

| Metric | Threshold | Current |
|---|---|---|
| Task success | `>=0.9` | 1.00 |
| Policy violation rate | `<=0` | 0.00 |

A `cost_per_task` ceiling is also enforced; it is computed from the mock model's token estimates, so treat it as a regression signal rather than a real cost.

## Run

```bash
python -m evals --project 05             # run the cases, refresh scores.json
python -m evals --project 05 --no-write  # gate only (what CI does)
python -m evals --project 05 -v          # list failing cases
```

Each case is executed by `invoice_match.eval_suite:run_case` in [`invoice_match/eval_suite.py`](../invoice_match/eval_suite.py).
