# `16-telecom-outage-care/evals/`: golden set and scores

Offline evaluation data for this project. The portfolio runner (`python -m evals`, see
[`/evals`](../../../evals/README.md)) feeds every case in `golden.jsonl` to the project's
`run_case` function, aggregates the metrics with [`shared/evals`](../../../shared/evals/README.md)
and gates on the thresholds declared in `doctrine.yaml`.

| File | What it does |
|---|---|
| [`golden.jsonl`](golden.jsonl) | Golden set: 19 cases, one JSON object per line with `id`, `input` and `expect`. Examples: `confirmed-outage-affects-customer`, `dual-homed-cell-survives`, `no-outage-ont-offline-dispatch`, `stale-oss-honest`, ... |
| [`scores.json`](scores.json) | Latest metrics, thresholds and pass/fail written by `python -m evals`. Read by `python -m shared.doctrine` to render `DOCTRINE.md` and the root README matrix; do not edit by hand. |

## Gate

Thresholds come from [`../doctrine.yaml`](../doctrine.yaml) (`eval.thresholds`). Current values
are from the checked-in `scores.json`:

| Metric | Threshold | Current |
|---|---|---|
| Task success | `>=0.95` | 1.00 |
| Groundedness | `>=0.95` | 1.00 |
| Policy violation rate | `<=0` | 0.00 |

A `cost_per_task` ceiling is also enforced; it is computed from the mock model's token estimates, so treat it as a regression signal rather than a real cost.

## Run

```bash
python -m evals --project 16             # run the cases, refresh scores.json
python -m evals --project 16 --no-write  # gate only (what CI does)
python -m evals --project 16 -v          # list failing cases
```

Each case is executed by `outage_care.eval_suite:run_case` in [`outage_care/eval_suite.py`](../outage_care/eval_suite.py).
