# `assessment-bank/infra`

Azure Container Apps, Cosmos DB and Entra External ID settings for the assessment bank. Not deployed.

| File | What it does |
|---|---|
| [`terraform/`](terraform/README.md) | Full stack, including the External ID app registration (`azuread`). |
| [`bicep/`](bicep/README.md) | The same Container Apps and Cosmos resources. The app registration stays in Terraform because it is a Microsoft Graph object. |
