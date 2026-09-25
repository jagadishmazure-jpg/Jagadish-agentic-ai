# `.github/workflows/`: continuous integration

GitHub Actions configuration for the portfolio. A single workflow runs the whole offline
quality bar on every push to `main` and on every pull request: lint, format check, the full
pytest suite against the deterministic mock LLM, the portfolio eval gate and the doctrine
promotion gate. No cloud credentials are needed because every project runs offline.
(GitHub renders this README when you browse the folder; Actions only reads the `.yml` files.)

| File | What it does |
|---|---|
| [`ci.yml`](ci.yml) | The `CI` workflow. Matrix over Python 3.11 and 3.13; installs the locked environment with `uv sync --locked --all-extras --group dev`, then runs `ruff check`, `ruff format --check`, `pytest`, `python -m evals --no-write`, the contract-review precision/recall gate (`projects/08-contract-review/evals/run_eval.py --min-precision 0.8 --min-recall 0.8`) and `python -m shared.doctrine validate`. All steps set `LLM_PROVIDER=mock`. |

## Reproduce CI locally

```bash
uv sync --locked --all-extras --group dev
export LLM_PROVIDER=mock
uv run ruff check . && uv run ruff format --check .
uv run pytest
uv run python -m evals --no-write
uv run python projects/08-contract-review/evals/run_eval.py --min-precision 0.8 --min-recall 0.8
uv run python -m shared.doctrine validate
```

## Design notes

- `python -m evals --no-write` compares fresh scores with the thresholds in each
  `doctrine.yaml` without rewriting the checked-in `evals/scores.json`, so a regression fails
  the build instead of silently updating the numbers.
- The doctrine gate also fails when a generated `DOCTRINE.md` or the compliance matrix in the
  top-level README is stale, so docs cannot drift from the cards.
