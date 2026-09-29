# `21-multi-agent-orchestration-patterns/evals/`: golden set, scores and pattern comparison

Offline evaluation data for this project. The portfolio runner (`python -m evals`, see
[`/evals`](../../../evals/README.md)) feeds every case in `golden.jsonl` to the project's
`run_case` function, aggregates the metrics with [`shared/evals`](../../../shared/evals/README.md)
and gates on the thresholds declared in `doctrine.yaml`. The comparison runner
(`python run.py --compare --write`) reuses the same harness and the same `business` cases for
every pattern.

| File | What it does |
|---|---|
| [`golden.jsonl`](golden.jsonl) | Golden set: 24 cases. 14 `business` cases (one per loan: approve, approve with conditions, decline, pend, committee referral, 2025 vs 2026 policy edition, delegated-authority limit) run through the default pattern (supervisor); 10 pinned cases exercise a specific pattern, fault, HITL answer or the intake guard. |
| [`scores.json`](scores.json) | Latest metrics, thresholds and pass/fail written by `python -m evals`. Read by `python -m shared.doctrine` to render `DOCTRINE.md` and the root README matrix; do not edit by hand. |
| [`comparison.json`](comparison.json) | Per-pattern quality, groundedness, violations, LLM calls, tokens, tool calls, turns and simulated latency on the business cases, plus the fault table. Written by `python run.py --compare --write`; `tests/test_comparison.py` fails if it is stale. |

## Gate

Thresholds come from [`../doctrine.yaml`](../doctrine.yaml) (`eval.thresholds`). Current values
are from the checked-in `scores.json`:

| Metric | Threshold | Current |
|---|---|---|
| Task success | `>=0.95` | 1.00 |
| Groundedness | `>=0.95` | 1.00 |
| Policy violation rate | `<=0` | 0.00 |

A `cost_per_task` ceiling is also enforced; it is computed from the mock model's token
estimates, so treat it as a regression signal rather than a real cost.

A case succeeds when the decision, the condition set and the required citations match, every
DTI/LTV figure in the memo equals the computed one, and the run ended `completed`. A violation
is a filed memo that contradicts policy, a double filing, a restricted or invented citation or
injected text in the memo.

## Run

```bash
python -m evals --project 21             # run the cases, refresh scores.json
python -m evals --project 21 --no-write  # gate only (what CI does)
python run.py --compare --check          # comparison.json + README table fresh?
```

Each case is executed by `orchestration_lab.eval_suite:run_case` in [`orchestration_lab/eval_suite.py`](../orchestration_lab/eval_suite.py).
