# Best practices: what is implemented and what is planned

A checklist of enterprise cloud and agentic AI practices for this portfolio. Each row links to the code that implements it and says honestly whether it is implemented, written but not deployed, or planned. Nothing here has been deployed to Azure.

**How to read the status column**

- **Implemented**: the code is in this repo and runs in the offline tests or in CI.
- **Written, not deployed**: the infrastructure or workflow code exists and passes validation (`bicep build`, `terraform validate` and `terraform test`, tflint, checkov, actionlint), but it has never run against a real Azure subscription.
- **Planned**: not in the repo yet. The note says what is missing.

## Enterprise cloud

| Practice | What this repo does | Status | Where |
|---|---|---|---|
| **Identity: OIDC and managed identity** | CI signs in with `azure/login` over OIDC (no client secret). The API container runs as a user-assigned managed identity, and `shared/llm.py` reaches Azure OpenAI keyless through `DefaultAzureCredential` and a bearer-token provider (an API key is used only if `AZURE_OPENAI_API_KEY` is set). The deployed app still defaults to the mock model unless `live_llm = true`. | CI + identity written, not deployed; keyless model auth implemented and unit-tested | [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml), [`identity module`](../infra/terraform/modules/identity/README.md), [`shared/llm.py`](../shared/llm.py), [ADR 0003](adr/0003-oidc-and-managed-identity.md) |
| **Least privilege** | In Azure, the app identity gets AcrPull and, only when `live_llm = true`, Cognitive Services OpenAI User on the Foundry account. In code, project 09 gives each tool its own identity and allow-list. | Written, not deployed; tool identities implemented | [`infra/terraform/main.tf`](../infra/terraform/main.tf), [`09 collections`](../projects/09-collections-agent/README.md) |
| **Networking** | The API is a small public HTTPS endpoint on Container Apps. There is no VNet or private endpoint for this stack. | Planned | [`containerapp module`](../infra/terraform/modules/containerapp/README.md) |
| **Secrets** | No secrets in the repo or in CI; settings are listed in `.env.example` with no values; Key Vault (RBAC) is provisioned for anything that cannot use Entra ID. gitleaks scans the full git history in CI, and GitHub secret scanning with push protection is on. | Implemented; Key Vault written, not deployed | [`.env.example`](../.env.example), [`ci.yml`](../.github/workflows/ci.yml), [`.gitleaksignore`](../.gitleaksignore), [`keyvault module`](../infra/terraform/modules/keyvault/README.md) |
| **Supply chain** | Every third-party action is pinned to a commit SHA with a version comment; every workflow has top-level read-only `permissions`; Dependabot opens weekly grouped updates for uv, Actions, Docker and Terraform; CodeQL scans Python and the workflows; Dependabot alerts and security updates are on; `main` has a ruleset that blocks force-push and deletion and requires CI on pull requests. No SBOM, image scan or build provenance yet. | Implemented; SBOM and signing planned | [`dependabot.yml`](../.github/dependabot.yml), [`codeql.yml`](../.github/workflows/codeql.yml), [`SECURITY.md`](../SECURITY.md) |
| **Tagging and naming** | CAF names (`rg-agentic-dev-eus2-001`) and six required tags, checked by `terraform test`. | Implemented (tests); written, not deployed | [`naming module`](../infra/terraform/modules/naming/README.md), [`plan tests`](../infra/terraform/tests/README.md) |
| **Cost controls** | Dev scales to zero, caps logs at 1 GB/day, uses Basic ACR and deploys no model unless `live_llm = true`. In code, a cost meter records tokens and estimated cost per run. Budgets and cost alerts are not defined yet. | Written, not deployed; cost meter implemented; budgets planned | [`envs`](../infra/terraform/envs/README.md), [`shared/observability.py`](../shared/observability.py) |
| **Infrastructure as code** | Terraform stack plus a Bicep twin. CI runs fmt, validate, offline `terraform test`, tflint, checkov and `bicep build`. | Implemented | [`infra/`](../infra/README.md), [`.github/workflows/infra.yml`](../.github/workflows/infra.yml), [ADR 0001](adr/0001-bicep-and-terraform.md) |
| **CI/CD gates** | Lint, 544 tests on Python 3.11 and 3.13, a gitleaks scan, the portfolio eval gate, the contract-review precision/recall gate and the doctrine promotion gate on every push. Deploy goes dev -> prod through a GitHub Environment meant to require reviewers; it is gated off and the Environments do not exist yet. | Implemented (CI); deploy written, not deployed | [`workflows`](../.github/workflows/README.md), [deployment.md](deployment.md), [ADR 0005](adr/0005-deploy-gated-off.md) |
| **Observability** | OpenTelemetry spans for graph, node, LLM and tool calls with thread id, identity, tokens and cost; OTLP export is optional. The IaC creates Log Analytics and App Insights, but the app does not export to App Insights yet. | Implemented (spans); App Insights export planned | [`shared/observability.py`](../shared/observability.py), [`monitoring module`](../infra/terraform/modules/monitoring/README.md) |
| **Disaster recovery** | The API is stateless and can be recreated from IaC and the promoted image. No backup, second region or restore drill. | Planned | [deployment.md](deployment.md) |

## Agentic AI

| Practice | What this repo does | Status | Where |
|---|---|---|---|
| **Human in the loop** | LangGraph `interrupt()` before risky actions: refunds (03), incident rollback (06), collections plans (09), purchase orders (10), claim reserves within authority (13), clinician sign-off (14), dual control on credit limits (15). | Implemented | [`03 refund`](../projects/03-refund-agent/README.md), [`14 prior auth`](../projects/14-healthcare-prior-auth/README.md) |
| **Evals and release gates** | Every project has a golden set; `python -m evals --no-write` fails CI below each project's thresholds, and the doctrine gate blocks promotion if a card, five-exit row or score is missing. | Implemented | [`evals/`](../evals/README.md), [`shared/evals`](../shared/evals/README.md), [`shared/doctrine`](../shared/doctrine/README.md), [ADR 0004](adr/0004-eval-gates-block-release.md) |
| **Guardrails and runtime safety** | Retrieved text is sanitised for injected instructions; guardrail middleware on the ReAct agent (06); circuit breakers, retry and a model fallback chain; chaos tests kill the model, retrieval or a system of record and assert the declared exit. | Implemented | [`shared/context`](../shared/context/README.md), [`shared/resilience.py`](../shared/resilience.py), [`shared/chaos.py`](../shared/chaos.py) |
| **Tool governance and MCP** | Systems of record are MCP servers reached only through a `ToolGateway` with an allow-list per identity, quotas, timeouts, breakers and schema validation. Project 12 adds an agent registry, promotion gate, per-tenant A2A policy and a kill switch. | Implemented | [`shared/tools`](../shared/tools/README.md), [`shared/mcp_servers`](../shared/mcp_servers/README.md), [`12 control plane`](../projects/12-agent-control-plane/README.md) |
| **Memory** | Thread state in LangGraph checkpointers; project 20 adds long-term memory (semantic, episodic, procedural) per user with a write policy (consent, poisoning checks, redaction, conflicts) and forget-on-request. | Implemented | [`20 memory agent`](../projects/20-long-term-memory-agent/README.md) |
| **Grounding** | Hybrid retrieval with ACL by principal and as-of validity, a token-budget packer and citations; project 01 grades retrieval and retries before answering. | Implemented | [`shared/context`](../shared/context/README.md), [`01 policy RAG`](../projects/01-policy-qa-rag/README.md) |
| **Tracing** | One trace per run across graph, nodes, LLM, tools and A2A hops, with `traceparent` and tenant propagation. | Implemented | [`shared/observability.py`](../shared/observability.py), [`shared/a2a`](../shared/a2a/README.md) |
| **Model versioning** | Project 19 has a model registry with a promotion gate and rollback; the LLM factory has a primary -> fallback deployment chain; model names and versions are pinned as IaC variables. | Implemented; IaC pins written, not deployed | [`19 fine-tune`](../projects/19-finetune-vs-prompting/README.md), [`shared/llm.py`](../shared/llm.py), [`infra/terraform/variables.tf`](../infra/terraform/variables.tf) |
| **Responsible AI** | PII redaction (02), PHI redaction in context and logs (14), consent and right to be forgotten (20), synthetic data only, and an owner, KPI and stop conditions on every doctrine card. No content-safety service is wired in. | Implemented; content safety service planned | [`02 triage`](../projects/02-ticket-triage/README.md), [`14 prior auth`](../projects/14-healthcare-prior-auth/README.md), [`20 memory`](../projects/20-long-term-memory-agent/README.md) |

## Known gaps, in priority order

- Export traces to App Insights from the deployed API.
- SBOM, image scan and signed build provenance for the API image.
- Budgets and cost alerts for the dev and prod resource groups.

Related: [architecture decisions](adr/README.md) · [deployment pipeline](deployment.md) · [security policy](../SECURITY.md) · [contributing](../CONTRIBUTING.md)
