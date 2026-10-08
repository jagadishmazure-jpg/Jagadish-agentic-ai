# `modules/alerts`

Azure Monitor alerting: one action group (optional on-call email), metric alert rules on the platform resources, KQL log alert rules on Application Insights, and a diagnostic setting per resource that sends `allLogs` and `AllMetrics` to the Log Analytics workspace. Mirrors [`../../../modules/alerts.bicep`](../../../modules/alerts.bicep). Written and validated offline (`terraform test`, checkov); not deployed.

| File | What it does |
|---|---|
| [`main.tf`](main.tf) | Resources (and module calls for a root stack). |
| [`outputs.tf`](outputs.tf) | Values exported to the caller / the pipeline. |
| [`variables.tf`](variables.tf) | Inputs with types, defaults and validation rules. |
| [`versions.tf`](versions.tf) | Terraform and provider version constraints. |
