# `shared/evals/`: offline eval harness

The library behind `python -m evals`. Each project ships `evals/golden.jsonl` (one case per
line with `id`, `input`, `expect`) and a `run_case(case) -> CaseResult` function in its
package. The harness runs every case offline, measures cost and tool calls from telemetry
deltas, aggregates the metrics and checks them against the thresholds declared in the
project's `doctrine.yaml`.

| File | What it does |
|---|---|
| [`__init__.py`](__init__.py) | Re-exports `METRICS`, `CaseResult`, `EvalReport`, `load_golden`, `run_suite`, `check_thresholds`. |
| [`harness.py`](harness.py) | `load_golden`, `run_suite`, `check_thresholds`, `case_results_json`, plus `CaseResult` and `EvalReport`. Metrics: `task_success`, `groundedness` (only for cases that produce cited text), `policy_violation_rate`, `tool_error_rate` (tool errors / gateway calls) and `cost_per_task` (estimated from token counts). |

## Notes

- Thresholds are strings such as `">=0.9"` or `"<=0"`; `check_thresholds` returns a list of
  human-readable violations, and an empty list means the project passes.
- `tool_error_rate` is high in some projects on purpose, because their golden sets inject
  system-of-record failures to prove the degrade paths.
- `cost_per_task` uses the mock model's token estimates, so it is a relative signal for
  regressions, not a real bill.

Run it through the CLI in [`evals/`](../../evals/README.md): `python -m evals`.
