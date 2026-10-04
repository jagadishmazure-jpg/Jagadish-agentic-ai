# ADR 0005: Ship the deploy pipeline switched off

- **Status:** Accepted

## Context

The repo should show a complete, reviewable path to Azure (build, dev, approval, prod, smoke tests, teardown), but there is no Azure subscription yet. A workflow that fails on every push, or one that could create billable resources by accident, would be worse than none.

## Decision

`deploy.yml` and `teardown.yml` exist and pass actionlint. Every job after `preflight` runs only when the repository variable `DEPLOY_ENABLED` is `true`, which is not set. `preflight` always runs and reports the gate in the job summary. Prod runs in a GitHub Environment meant to have required reviewers. The pipeline builds the portfolio API image, promotes it from the dev ACR to prod with `az acr import`, and smoke-tests `/healthz`, `/readyz` and `/projects`.

## Consequences

- Pushes to `main` show a green `deploy` run with skipped jobs, which is the honest state.
- The deploy, promotion and smoke steps have never run for real. They are validated only by actionlint and by running `deploy.sh` subcommands locally where possible.
- Turning it on is a deliberate step: create the Environments and reviewers, the federated credentials and the state storage, set the variables, then set `DEPLOY_ENABLED=true`.
