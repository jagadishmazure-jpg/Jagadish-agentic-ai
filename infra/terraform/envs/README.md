# `infra/terraform/envs`

`*.tfvars` choose the dev (cost-min) or prod shape; `*.backend.hcl` hold the state key for the partial backend.

| File | What it does |
|---|---|
| [`dev.backend.hcl`](dev.backend.hcl) | Partial backend config for dev state (state key + Entra auth; storage names filled at init). |
| [`dev.tfvars`](dev.tfvars) | dev values: the cost-min profile. |
| [`prod.backend.hcl`](prod.backend.hcl) | Partial backend config for prod state. |
| [`prod.tfvars`](prod.tfvars) | prod values: always-on / hardened settings. |
