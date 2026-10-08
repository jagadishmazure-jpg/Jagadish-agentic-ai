# `infra/bicep`

The Bicep version of [`../terraform`](../terraform/README.md), deployed at resource-group scope. `bicep build main.bicep` compiles with no warnings (CI checks it). Nothing has been deployed.

| File | What it does |
|---|---|
| [`main.bicep`](main.bicep) | Identity, logs, Key Vault, ACR, Container Apps environment + app, optional Foundry account and deployments; optional private networking (`privateNetworking`), alert rules and diagnostic settings (`enableAlerts`, on) and Defender for Cloud plans (`enableDefender`, off). |
| [`modules/`](modules/README.md) | Alerts, Defender, network (VNet + NSG + DNS zones) and private-endpoint modules. |
