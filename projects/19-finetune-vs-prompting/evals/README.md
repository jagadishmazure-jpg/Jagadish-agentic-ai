# `19-finetune-vs-prompting/evals/`: golden set, comparison and scores

Offline evaluation data for this project. The portfolio runner (`python -m evals`, see
[`/evals`](../../../evals/README.md)) feeds every case in `golden.jsonl` to the project's
`run_case` function, aggregates the metrics with [`shared/evals`](../../../shared/evals/README.md)
and gates on the thresholds declared in `doctrine.yaml`. The golden set tests the serving graph
end to end with the registry champion; the fine-tuned vs prompted comparison on the full
val/test splits is in `comparison.json`.

| File | What it does |
|---|---|
| [`golden.jsonl`](golden.jsonl) | Golden set: 14 cases, one JSON object per line with `id`, `input` and `expect`. Examples: `w2-canonical`, `ocr-garbled-w2`, `utility-bill-not-in-taxonomy`, `injected-instructions`, `pii-heavy-paystub`, ... |
| [`comparison.json`](comparison.json) | Written by `run.py compare --write`: dataset summary, training stats, registered versions, accuracy / macro-F1 / per-class F1 / confusion / latency / tokens per split and variant, the gate result and the champion. The project README's results table is rendered from it. |
| [`scores.json`](scores.json) | Latest metrics, thresholds and pass/fail written by `python -m evals`. Read by `python -m shared.doctrine` to render `DOCTRINE.md` and the root README matrix; do not edit by hand. |

## Gate

Thresholds come from [`../doctrine.yaml`](../doctrine.yaml) (`eval.thresholds`). Current values
are from the checked-in `scores.json`:

| Metric | Threshold | Current |
|---|---|---|
| Task success | `>=0.9` | 1.00 |
| Policy violation rate | `<=0` | 0.00 |
| Tool error rate | `<=0.05` | 0.00 |

A `cost_per_task` ceiling is also enforced; it is computed from the mock model's token estimates, so treat it as a regression signal rather than a real cost. It reads 0 here because the champion is the local fine-tuned head, which makes no LLM call. The model promotion gate (fine-tuned vs champion on the validation split) is separate and lives in [`finetune_lab/registry.py`](../finetune_lab/registry.py).

## Run

```bash
python -m evals --project 19             # run the cases, refresh scores.json
python -m evals --project 19 --no-write  # gate only (what CI does)
python -m evals --project 19 -v          # list failing cases
python projects/19-finetune-vs-prompting/run.py compare   # fine-tuned vs prompted comparison + promotion gate
```

Each case is executed by `finetune_lab.eval_suite:run_case` in [`finetune_lab/eval_suite.py`](../finetune_lab/eval_suite.py).
