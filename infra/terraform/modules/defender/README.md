# `modules/defender`

Opt-in Microsoft Defender for Cloud plans (`Standard` tier) for the resource types this workload uses. Defender plans apply to the whole subscription and are billed per protected resource, so the root stack calls this module only when `enable_defender = true` (default `false`). Mirrors the `Microsoft.Security/pricings` resources in [`../../../main.bicep`](../../../main.bicep). Not deployed.

| File | What it does |
|---|---|
| [`main.tf`](main.tf) | Resources (and module calls for a root stack). |
| [`outputs.tf`](outputs.tf) | Values exported to the caller / the pipeline. |
| [`variables.tf`](variables.tf) | Inputs with types, defaults and validation rules. |
| [`versions.tf`](versions.tf) | Terraform and provider version constraints. |
