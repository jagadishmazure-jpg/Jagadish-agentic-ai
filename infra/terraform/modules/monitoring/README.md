# `modules/monitoring`

Log Analytics workspace (PerGB2018, optional daily cap) and a workspace-based Application Insights component.

| File | What it does |
|---|---|
| [`main.tf`](main.tf) | Resources (and module calls for a root stack). |
| [`outputs.tf`](outputs.tf) | Values exported to the caller / the pipeline. |
| [`variables.tf`](variables.tf) | Inputs with types, defaults and validation rules. |
| [`versions.tf`](versions.tf) | Terraform and provider version constraints. |
