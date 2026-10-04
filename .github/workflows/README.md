# `.github/workflows/`: CI, infrastructure checks and the gated deploy pipeline

GitHub Actions configuration for the portfolio. `ci.yml` runs the whole offline
quality bar on every push to `main` and on every pull request: lint, format check, the full
pytest suite against the deterministic mock LLM, the portfolio eval gate and the doctrine
promotion gate. No cloud credentials are needed because every project runs offline.
(GitHub renders this README when you browse the folder; Actions only reads the `.yml` files.)

| File | What it does |
|---|---|
| [`ci.yml`](ci.yml) | The `CI` workflow. Matrix over Python 3.11 and 3.13; installs the locked environment with `uv sync --locked --all-extras --group dev`, then runs `ruff check`, `ruff format --check`, `pytest`, `python -m evals --no-write`, the contract-review precision/recall gate (`projects/08-contract-review/evals/run_eval.py --min-precision 0.8 --min-recall 0.8`) and `python -m shared.doctrine validate`. All steps set `LLM_PROVIDER=mock`. A separate `docs` job runs `python scripts/render_docs.py --check`, so pasted output and code excerpts in every README must match the code. |
| [`infra.yml`](infra.yml) | On push/PR: `terraform fmt -check`, `init -backend=false`, `validate` and `terraform test` (mocked providers) for `infra/terraform`; tflint; checkov with [`.checkov.yaml`](../../.checkov.yaml); `bicep build` of `infra/bicep/main.bicep`; builds the API image and smoke-runs `/healthz`. `terraform plan` runs only when the Azure OIDC variables exist, otherwise it passes with a notice. |
| [`deploy.yml`](deploy.yml) | Push to `main` or manual (`deploy_tool`: `terraform` / `bicep`): `preflight` reports the gate, then `build` -> `deploy-dev` (environment `dev`) -> `deploy-prod` (environment `prod`, required reviewers). OIDC login via `azure/login` (no client secret), image promotion with `az acr import`, smoke tests. Every job after `preflight` is skipped unless the repository variable `DEPLOY_ENABLED` is `true`; it is not set. See [`docs/deployment.md`](../../docs/deployment.md). |
| [`teardown.yml`](teardown.yml) | Manual only: destroys one environment with the tool that created it, after typing the environment name again. Same gate; prod needs approval. |

## Reproduce CI locally

```bash
uv sync --locked --all-extras --group dev
export LLM_PROVIDER=mock
uv run ruff check . && uv run ruff format --check .
uv run pytest
uv run python -m evals --no-write
uv run python projects/08-contract-review/evals/run_eval.py --min-precision 0.8 --min-recall 0.8
uv run python -m shared.doctrine validate
uv run python scripts/render_docs.py --check
```

## Design notes

- `python -m evals --no-write` compares fresh scores with the thresholds in each
  `doctrine.yaml` without rewriting the checked-in `evals/scores.json`, so a regression fails
  the build instead of silently updating the numbers.
- The doctrine gate also fails when a generated `DOCTRINE.md` or the compliance matrix in the
  top-level README is stale, so docs cannot drift from the cards.
