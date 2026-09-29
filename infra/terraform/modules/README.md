# `infra/terraform/modules`

Modules called by the root stack. Each takes `resource_group_name`, `location` and `tags`.

| File | What it does |
|---|---|
| [`containerapp/`](containerapp/README.md) | One Container App (HTTP service or KEDA queue worker) on a user-assigned identity, pulling from ACR with that identity. The image is ignored after creation because the pipeline rolls images. |
| [`containerapps-env/`](containerapps-env/README.md) | Container Apps managed environment on the Consumption workload profile, logging to Log Analytics; optional VNet integration. |
| [`foundry/`](foundry/README.md) | Microsoft Foundry: AIServices account (keyless, project management on), a Foundry project and optional AI Search connection via `azapi`, and model deployments via `azurerm_cognitive_deployment`. |
| [`identity/`](identity/README.md) | User-assigned managed identities, one per key in a static map, so role assignments can be keyed before the principal ids exist. |
| [`keyvault/`](keyvault/README.md) | Key Vault in RBAC mode (no access policies), soft delete 7 days, purge protection as a variable, and `Key Vault Secrets User` for the given workload identities. |
| [`monitoring/`](monitoring/README.md) | Log Analytics workspace (PerGB2018, optional daily cap) and a workspace-based Application Insights component. |
| [`naming/`](naming/README.md) | CAF naming helper: `<type>-<workload>-<env>-<region>-<instance>` (for example `rg-agentplat-dev-eus2-001`), compressed forms for Key Vault (24 chars, region dropped), ACR and Storage (alphanumeric), and an optional suffix for globally unique names. No resources. |
| [`registry/`](registry/README.md) | Azure Container Registry with the admin user disabled; `AcrPull` for the workload identities. |
