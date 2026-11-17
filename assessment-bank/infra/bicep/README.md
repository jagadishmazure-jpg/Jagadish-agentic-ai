# `assessment-bank/infra/bicep`

The Container Apps and Cosmos half of the assessment stack. `bicep build` compiles with no warnings.

The Entra External ID app registration is not in this file. Graph applications are not resource-group resources; the Terraform twin creates the registration when the azuread provider is aimed at the external tenant. Pass `entraTenantId`, `entraTenantSubdomain` and `entraClientId` so the container gets the same environment variables.

| File | What it does |
|---|---|
| [`main.bicep`](main.bicep) | Log Analytics, identity, serverless Cosmos (keys off, `/learnerId`), Container App scaled to zero, External ID env vars. |

```bash
bicep build assessment-bank/infra/bicep/main.bicep --stdout > /dev/null
```
