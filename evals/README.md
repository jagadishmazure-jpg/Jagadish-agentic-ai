# `evals/`: portfolio-wide eval runner

Entry point for running every project's golden eval set in one command. It loads each
project's `doctrine.yaml`, runs the golden cases listed there through the project's own
`eval_suite.run_case`, prints one row of metrics per project and exits non-zero if any
project breaks its thresholds. The metric logic itself lives in
[`shared/evals`](../shared/evals/README.md); this folder is only the CLI.

| File | What it does |
|---|---|
| [`__init__.py`](__init__.py) | Package marker so the runner can be invoked as `python -m evals`. |
| [`__main__.py`](__main__.py) | `main()`: discovers projects via `shared.doctrine.card.project_dirs()`, runs `shared.evals.harness.run_suite` for each, prints the table, writes `projects/*/evals/scores.json` (unless `--no-write`) and returns 1 on any threshold violation. Flags: `--project NN`, `--no-write`, `--live` (use the configured real LLM instead of forcing the mock), `-v`. |

## Usage

```bash
python -m evals                 # all projects; refreshes projects/*/evals/scores.json
python -m evals --project 03    # one project (prefix match on the folder name)
python -m evals --no-write      # CI mode: gate only, leave scores.json untouched
python -m evals --project 08 -v # also list every failing case
```

Without `--live` the runner sets `LLM_PROVIDER=mock` and disables retry back-off sleeps, so
results are deterministic and fast. The refreshed `scores.json` files feed
`python -m shared.doctrine render`, which regenerates each project's `DOCTRINE.md` and the
compliance matrix in the top-level README.
