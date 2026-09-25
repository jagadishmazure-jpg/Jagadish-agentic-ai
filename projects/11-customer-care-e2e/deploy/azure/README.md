# Azure deployment notes (skeleton, not deployed)

`main.bicep` sketches the production topology for the care agent. It has not been deployed
or validated against a subscription; treat it as a starting point.

| Plane | Local (docker-compose) | Azure |
|---|---|---|
| Experience | `care-bff` container: auth stub, channel claim, token-bucket limit, SSE | API Management (JWT validation, `rate-limit-by-key` per tenant + channel) in front of the `care-bff` Container App |
| Agent | LangGraph care graph inside the BFF, `MemorySaver` checkpoints | Same image; swap `MemorySaver` for a durable checkpointer (Postgres / Cosmos DB) so HITL survives restarts |
| Knowledge | In-memory care-policy corpus via the shared context builder | Azure AI Search index (hybrid + semantic ranker) with security-trimmed fields; same `ContextBuilder` contract |
| Data | `mcp-oms`, `mcp-crm`, `mcp-payments` containers over streamable HTTP | Internal-only Container Apps (no public ingress); managed identity to the real OMS/CRM/payment APIs |
| Outbox | In-memory `Outbox` + `worker.dispatch` | Service Bus queue `refund-commands` with duplicate detection on the idempotency key; a KEDA-scaled worker app drains it |

## Deployment checklist

1. Build and push the image: `docker build -f projects/11-customer-care-e2e/Dockerfile -t <acr>/care-e2e:<sha> .`
2. `az deployment group create -g <rg> -f deploy/azure/main.bicep -p image=... openAiEndpoint=... openAiDeployment=... openAiFallbackDeployment=...`
3. Give the managed identity `Cognitive Services OpenAI User` on the Azure OpenAI resource
   (keyless) and `Azure Service Bus Data Sender/Receiver` on the namespace.
4. Replace the BFF token stub with APIM-validated JWT claims (`sub`, `tenant`, `channels`).
5. Point `OTEL_EXPORTER_OTLP_ENDPOINT` (or the Azure Monitor exporter) at Application Insights.
6. Gate the release on `python -m evals --project 11` and `python -m shared.doctrine validate`.

## Things the skeleton deliberately leaves out

- The worker app for the Service Bus queue, private endpoints, VNet integration and Key Vault.
- A durable LangGraph checkpointer.
- A scheduled job (Container Apps job) calling `POST /v1/ops/sla-sweep` every few minutes.
