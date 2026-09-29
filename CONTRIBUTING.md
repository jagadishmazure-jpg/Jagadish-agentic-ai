# Contributing

This is a personal portfolio, but issues and pull requests are welcome. The bar for a change is the same one CI enforces.

## Set up

```bash
uv sync --locked --all-extras --group dev
export LLM_PROVIDER=mock
```

## Checks to run before a pull request

```bash
uv run ruff check . && uv run ruff format --check .
uv run pytest
uv run python -m evals --no-write
uv run python projects/08-contract-review/evals/run_eval.py --min-precision 0.8 --min-recall 0.8
uv run python -m shared.doctrine validate
```

Infrastructure (offline, no Azure login needed):

```bash
terraform -chdir=<stack> init -backend=false && terraform -chdir=<stack> validate && terraform -chdir=<stack> test
bicep build <file>.bicep --stdout > /dev/null
```

## Conventions

- Keep everything runnable offline: new code needs a mock or stand-in and a test that uses it.
- Use only synthetic data. Never commit real customer data, personal email addresses, keys, connection strings or `.tfstate` files.
- Every folder has a `README.md` with a `| File | What it does |` table; add a row when you add a file.
- Commit messages follow Conventional Commits (`feat:`, `fix:`, `docs:`, `ci:`, `build:`, `test:`), with a scope where it helps (`feat(infra): ...`).
- Infrastructure changes go into both Bicep and Terraform, or the README says why they differ.
- Docs describe what the code does today. Mark anything else as planned. Numbers (test counts, scores, latencies) must come from a real run.
- Record significant design choices as an ADR in [`docs/adr/`](docs/adr/README.md) and add a line to [`CHANGELOG.md`](CHANGELOG.md).
- Each project keeps a `doctrine.yaml`; after changing it run `python -m shared.doctrine render` so `DOCTRINE.md` and the README matrix stay current.
- Do not edit the README between the `doctrine-matrix` markers by hand; it is generated.

## Pull request checklist

- [ ] CI is green (`ci`, `infra`; `deploy` only reports its gate)
- [ ] Tests added or updated, and counts in READMEs updated if they changed
- [ ] Folder README tables and links updated
- [ ] No secrets, personal data or generated state files
- [ ] `CHANGELOG.md` entry under **Unreleased**

Security issues: see [`SECURITY.md`](SECURITY.md), not the issue tracker.
