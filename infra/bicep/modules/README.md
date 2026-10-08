# `infra/bicep/modules`

Modules called by [`../main.bicep`](../main.bicep). Each mirrors a Terraform module in [`../../terraform/modules`](../../terraform/modules/README.md). Built offline in CI (`bicep build`, warnings fail); not deployed.

| File | What it does |
|---|---|
| [`alerts.bicep`](alerts.bicep) | Azure Monitor action group (optional on-call email), metric alert rules and KQL alert rules on Application Insights. |
| [`defender.bicep`](defender.bicep) | Opt-in Defender for Cloud plans at subscription scope (`enableDefender`, off by default: subscription-wide and billed). |
| [`network.bicep`](network.bicep) | Optional private networking: VNet with a Container Apps subnet and a private-endpoint subnet, one NSG on both, linked private DNS zones. |
| [`private-endpoint.bicep`](private-endpoint.bicep) | One private endpoint plus its private DNS zone group. |
