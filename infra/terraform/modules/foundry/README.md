# `modules/foundry`

Microsoft Foundry: AIServices account (keyless, project management on), a Foundry project and optional AI Search connection via `azapi`, and model deployments via `azurerm_cognitive_deployment`.

| File | What it does |
|---|---|
| [`main.tf`](main.tf) | Resources (and module calls for a root stack). |
| [`outputs.tf`](outputs.tf) | Values exported to the caller / the pipeline. |
| [`variables.tf`](variables.tf) | Inputs with types, defaults and validation rules. |
| [`versions.tf`](versions.tf) | Terraform and provider version constraints. |
