# `assessment-bank/infra/terraform`

Container Apps (scale to zero), a serverless Cosmos account with local keys off, a SQL container partitioned on `/learnerId`, a data-plane role for the app identity, and an Entra app registration. Apply with the azuread provider signed into the **External ID** tenant so learners exist in that tenant. The container authority is `https://<subdomain>.ciamlogin.com/<tenant>/v2.0`.

Nothing has been applied. `terraform test` uses mocked providers.

| File | What it does |
|---|---|
| [`main.tf`](main.tf) | Resource group, logs, identity, app registration, Cosmos, Container App. |
| [`outputs.tf`](outputs.tf) | Authority, client id, Cosmos endpoint, app name. |
| [`providers.tf`](providers.tf) | `azurerm` and `azuread`. |
| [`tests/`](tests/README.md) | Offline plan test. |
| [`variables.tf`](variables.tf) | Region, image, Cosmos name, External ID subdomain and tenant. |
| [`versions.tf`](versions.tf) | Provider constraints. |
| [`.terraform.lock.hcl`](.terraform.lock.hcl) | Locked providers. |

```bash
terraform -chdir=assessment-bank/infra/terraform init -backend=false
terraform -chdir=assessment-bank/infra/terraform test
```
