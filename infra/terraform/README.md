# `infra/terraform`: hosting the portfolio API on Azure

The portfolio is a set of offline agent projects, so there is no large platform to deploy. This stack hosts the small FastAPI service in [`shared/api`](../../shared/api/README.md) (list projects, read eval scores, rerun a project's golden set) on Azure Container Apps: a user-assigned managed identity with `AcrPull`, Log Analytics + App Insights, Key Vault (RBAC), ACR, a scale-to-zero Container Apps environment and, when `live_llm = true`, an Azure AI Foundry account with a primary and a fallback model deployment and `Cognitive Services OpenAI User` for the identity. [`../bicep/main.bicep`](../bicep/main.bicep) is the same stack in Bicep.

**Live model mode is opt-in:** with `live_llm = true` the app gets `LLM_PROVIDER=azure`, `PORTFOLIO_ALLOW_LIVE=1`, `AZURE_CLIENT_ID` and the Cognitive Services OpenAI User role, and `shared/llm.py` authenticates keyless through `DefaultAzureCredential` (no key is stored). Otherwise the deployed app runs the deterministic mock (`LLM_PROVIDER=mock`). Neither mode has been applied.

## Bicep or Terraform?

Both toolchains describe the same resources, so the choice is about the client, not the design:

| Pick Bicep when | Pick Terraform when |
|---|---|
| The estate is Azure-only and the team already uses `azd`, ARM deployment history and Azure Policy. | The client already runs Terraform (platform team, module registry, Terraform Cloud / Enterprise, Spacelift, Atlantis). |
| You need a new resource API version the day it ships (Bicep types come straight from the ARM specs). | Several clouds or SaaS providers (GitHub, Entra, Datadog) must be managed from one workflow. |
| You want no state file to secure: ARM is the source of truth, `what-if` previews changes. | Reviewers want a `plan` in every pull request and state-based drift detection. |

Trade-offs to state up front:

- **State.** Terraform needs a secured remote state (here: Azure Storage with Entra ID auth, no account keys). Bicep has none to lose or leak, but it also has no drift report beyond `what-if`.
- **New features.** `azurerm` lags new Azure APIs by weeks. The `azapi` provider fills that gap by calling ARM directly with the same API versions Bicep uses; it is used here only where needed.
- **One source of truth per environment.** Pick one tool per environment and stay with it. Both tools can target the same subscription, but they must never manage the same resource group, or each will try to undo the other's changes.

## Naming, tags and the cost-min profile

- **Names** follow the Cloud Adoption Framework pattern `<type>-<workload>-<env>-<region>-<instance>`, for example `rg-agentic-dev-eus2-001`. Key Vault drops the region (24-character limit); ACR and Storage use the alphanumeric form. Set `name_suffix` when forking so globally unique names don't collide.
- **Tags** on every resource group and resource: `env`, `owner`, `project`, `cost-center`, plus `workload` and `managed-by`. Override `owner` / `cost_center` per client in the tfvars.
- **Profiles.** `envs/dev.tfvars` selects the cost-min profile (scale-to-zero app, Basic ACR, 1 GB/day log cap, no model deployment). `envs/prod.tfvars` selects the hardened/always-on shape (one warm replica (up to 5), higher model capacity when `live_llm` is on, no log cap, Key Vault purge protection (ACR stays Basic in both)). Check the SKUs against the client's pricing agreement before any apply.

## Remote state (one-time bootstrap)

`backend.tf` is a partial `azurerm` backend. Create the storage once per subscription (or per client landing zone), with shared keys off so only Entra ID principals can read state:

```bash
az group create -n rg-tfstate-shared-eus2-001 -l eastus2 --tags env=shared owner=<you> project=tfstate cost-center=<cc>
az storage account create -n <globally-unique-name> -g rg-tfstate-shared-eus2-001 -l eastus2 \
  --sku Standard_ZRS --min-tls-version TLS1_2 --allow-blob-public-access false --allow-shared-key-access false
az storage container create --account-name <name> -n tfstate --auth-mode login
# the deploying identity needs "Storage Blob Data Contributor" on the container
```

Then pass the names at init (the pipeline reads them from the `TFSTATE_RESOURCE_GROUP` / `TFSTATE_STORAGE_ACCOUNT` variables):

```bash
terraform init -backend-config=envs/dev.backend.hcl \
  -backend-config=resource_group_name=rg-tfstate-shared-eus2-001 -backend-config=storage_account_name=<name>
```

## Validate locally (no Azure needed)

```bash
terraform init -backend=false
terraform fmt -check -recursive
terraform validate
terraform test          # plans with mocked providers and checks names, tags and profile shape
tflint --init && tflint --recursive
checkov -d . --config-file ../../.checkov.yaml
```

**Status:** validated offline only (the commands above run in CI on every pull request). No `apply` has been run: there is no Azure subscription yet.

## Files

| File | What it does |
|---|---|
| [`envs/`](envs/README.md) | dev / prod tfvars and partial backend configs. |
| [`modules/`](modules/README.md) | Reusable modules. |
| [`tests/`](tests/README.md) | Offline `terraform test` plans with a mocked provider. |
| [`.terraform.lock.hcl`](.terraform.lock.hcl) | Provider lock file (exact versions and checksums) so CI and laptops resolve the same providers. |
| [`.tflint.hcl`](.tflint.hcl) | tflint configuration (terraform recommended preset + azurerm ruleset). |
| [`backend.tf`](backend.tf) | Empty `azurerm` backend block (partial config); coordinates are passed with `-backend-config` at init. |
| [`locals.tf`](locals.tf) | Derived values: cost profile table, effective SKUs, the tag set, workload lists. |
| [`main.tf`](main.tf) | Resources (and module calls for a root stack). |
| [`outputs.tf`](outputs.tf) | Values exported to the caller / the pipeline. |
| [`providers.tf`](providers.tf) | Provider configuration. Credentials come from the environment (`az login` locally, OIDC in Actions); no secrets in code. |
| [`variables.tf`](variables.tf) | Inputs with types, defaults and validation rules. |
| [`versions.tf`](versions.tf) | Terraform and provider version constraints. |
