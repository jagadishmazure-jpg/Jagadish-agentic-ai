# `infra`

Infrastructure for hosting the portfolio API. See [`docs/deployment.md`](../docs/deployment.md) for the pipeline. Project 11 keeps its own skeleton Bicep in `projects/11-customer-care-e2e/deploy/azure/`, which is not part of this pipeline.

| File | What it does |
|---|---|
| [`bicep/`](bicep/README.md) | The same stack in Bicep. |
| [`terraform/`](terraform/README.md) | Terraform stack (primary), CAF names, dev/prod tfvars, offline plan tests. |
