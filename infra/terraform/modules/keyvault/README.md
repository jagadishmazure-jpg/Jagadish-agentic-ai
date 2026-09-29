# `modules/keyvault`

Key Vault in RBAC mode (no access policies), soft delete 7 days, purge protection as a variable, and `Key Vault Secrets User` for the given workload identities.

| File | What it does |
|---|---|
| [`main.tf`](main.tf) | Resources (and module calls for a root stack). |
| [`outputs.tf`](outputs.tf) | Values exported to the caller / the pipeline. |
| [`variables.tf`](variables.tf) | Inputs with types, defaults and validation rules. |
| [`versions.tf`](versions.tf) | Terraform and provider version constraints. |
