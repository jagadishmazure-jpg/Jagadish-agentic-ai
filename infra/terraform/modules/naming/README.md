# `modules/naming`

CAF naming helper: `<type>-<workload>-<env>-<region>-<instance>` (for example `rg-agentplat-dev-eus2-001`), compressed forms for Key Vault (24 chars, region dropped), ACR and Storage (alphanumeric), and an optional suffix for globally unique names. No resources.

| File | What it does |
|---|---|
| [`main.tf`](main.tf) | Resources (and module calls for a root stack). |
| [`outputs.tf`](outputs.tf) | Values exported to the caller / the pipeline. |
| [`variables.tf`](variables.tf) | Inputs with types, defaults and validation rules. |
| [`versions.tf`](versions.tf) | Terraform and provider version constraints. |
