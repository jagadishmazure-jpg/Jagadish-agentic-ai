# Deployment: GitHub Actions, OIDC, dev -> prod

This repository deploys with **GitHub Actions** (not Azure DevOps). Infrastructure can be created with **Bicep or Terraform**; the pipeline takes a `deploy_tool` input. Azure login uses **OpenID Connect** (workload identity federation): GitHub issues a short-lived token, Entra ID trusts it through a federated credential, and no client secret exists anywhere.

> **Status: nothing has been deployed.** There is no Azure subscription yet. Every deploy job is gated behind the repository variable `DEPLOY_ENABLED`, which is **not set**, so on each push to `main` the deploy workflow reports the gate and skips its jobs. The pull-request checks (format, validate, offline plan tests, lint, security scan, image build) run for real on every change.

## Workflows

| Workflow | Trigger | What it does |
|---|---|---|
| [`ci.yml`](../.github/workflows/ci.yml) | push to `main`, pull requests | The application checks (lint, tests, eval gates, doc drift) and a gitleaks scan of the full git history. |
| [`codeql.yml`](../.github/workflows/codeql.yml) | push to `main`, pull requests, weekly | CodeQL analysis of the Python code and of the workflow files; findings go to the Security tab. |
| [`infra.yml`](../.github/workflows/infra.yml) | push to `main`, pull requests, manual | `terraform fmt -check`, `init -backend=false`, `validate`, `terraform test` (mocked providers), tflint, checkov, container build + local smoke, a Trivy image scan (fixable HIGH/CRITICAL fail), an image SBOM and, on `main`, keyless build provenance for the image archive. `terraform plan` runs only if the Azure OIDC variables exist; otherwise the job logs a notice and passes, and validation is still enforced. |
| [`deploy.yml`](../.github/workflows/deploy.yml) | push to `main`, manual (`deploy_tool`: `terraform` or `bicep`) | Build the image(s), provision `dev`, push, roll, smoke test; then, after approval, provision `prod`, promote the same image, roll, smoke test. Gated by `DEPLOY_ENABLED == 'true'`. |
| [`teardown.yml`](../.github/workflows/teardown.yml) | manual only | Destroys one environment with the tool that created it. Gated by `DEPLOY_ENABLED`, runs in the matching GitHub Environment (so prod teardown also needs approval) and requires typing the environment name again. |

## Pipeline

```mermaid
flowchart LR
    PR[pull request] --> V[infra.yml: fmt, validate, terraform test, tflint, checkov, image build]:::gate
    V -->|OIDC vars set?| PL[terraform plan dev]
    V -->|no creds| SK[plan skipped with a notice]
    M[push to main / manual run] --> PF[preflight: report DEPLOY_ENABLED]
    PF --> B
    B[build: docker build + local /healthz smoke + save image]:::gate --> D1
    D1[deploy-dev: environment dev, OIDC login, provision with bicep or terraform]
    D1 --> P1[push image to dev ACR]
    P1 --> R1[roll Container Apps]
    R1 --> S1[smoke tests dev]
    S1 --> A{prod environment: required reviewers approve}:::approval
    A --> D2[deploy-prod: OIDC login, provision prod]
    D2 --> I2[import same image from dev ACR]
    I2 --> R2[roll Container Apps]
    R2 --> S2[smoke tests prod]
    T[teardown.yml, manual + confirm] -.-> D1
    T -.-> D2
    classDef gate fill:#eef,stroke:#446
    classDef approval fill:#fee,stroke:#a44
```

**Infrastructure.** `deploy_tool=terraform` applies [`infra/terraform`](../infra/terraform/README.md) with `envs/<env>.tfvars` and remote state; `deploy_tool=bicep` creates the resource group and runs `az deployment group create` on [`infra/bicep/main.bicep`](../infra/bicep/main.bicep).

**Image.** The root [`Dockerfile`](../Dockerfile) packages the portfolio API ([`shared/api`](../shared/api/README.md)). It is built per commit, smoke-tested locally, pushed to the dev ACR and promoted to prod with `az acr import`, so prod runs the exact bytes that passed dev.

**Smoke tests.** After each roll the pipeline polls `/healthz` on the app's public URL, then checks `/readyz` and that `/projects` returns a non-empty catalog.

## One-time setup (when a subscription exists)

Nothing below has been done yet; it is the checklist for the first real deployment.

1. **Identities.** Create one Entra app registration (or user-assigned managed identity) per environment, for example `gh-portfolio-dev` and `gh-portfolio-prod`. Give each a service principal.
2. **Federated credentials** (no secrets). On each identity add a GitHub credential with issuer `https://token.actions.githubusercontent.com` and audience `api://AzureADTokenExchange`:
   - dev deploy: subject `repo:jagadishmazure-jpg/Jagadish-agentic-ai:environment:dev`
   - prod deploy: subject `repo:jagadishmazure-jpg/Jagadish-agentic-ai:environment:prod`
   - PR plans (optional, read-only identity): subject `repo:jagadishmazure-jpg/Jagadish-agentic-ai:pull_request`

   ```bash
   az ad app federated-credential create --id <app-object-id> --parameters '{
     "name": "gh-dev", "issuer": "https://token.actions.githubusercontent.com",
     "subject": "repo:jagadishmazure-jpg/Jagadish-agentic-ai:environment:dev",
     "audiences": ["api://AzureADTokenExchange"] }'
   ```
3. **RBAC, least privilege.** Scope each identity to its own subscription or resource group: `Contributor` plus `Role Based Access Control Administrator` with a condition that limits it to the data-plane roles the stack assigns, and `Storage Blob Data Contributor` on the Terraform state container. The PR-plan identity gets `Reader` and state read access only.
4. **Terraform state.** Create the state storage account and container once (commands in the Terraform README).
5. **GitHub Environments.** In *Settings -> Environments* create `dev` and `prod`. On `prod` add **required reviewers** (at least one person other than the author where possible), enable *prevent self-review*, and restrict deployment branches to `main`. Optionally add a wait timer.
6. **Variables** (*Settings -> Secrets and variables -> Actions -> Variables*; no secrets needed). Set `AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` on each environment (different client ids for dev and prod), and `TFSTATE_RESOURCE_GROUP`, `TFSTATE_STORAGE_ACCOUNT` (optional `TFSTATE_CONTAINER`, `AZURE_LOCATION`, `DEPLOY_TOOL`) at repository level.
7. **Turn it on** by setting the repository variable `DEPLOY_ENABLED` to `true`. Leave it unset until steps 1 to 6 are done and reviewed.

## Rollback and teardown

- **Rollback:** re-run `deploy.yml` from an earlier commit (the image tag is the commit SHA), or `az containerapp revision activate` a previous revision.
- **Teardown:** run `teardown.yml`, pick the environment and tool, and type the environment name to confirm. Dev purges soft-deleted Key Vaults and AI accounts; prod keeps purge protection on.

## What a forward deployed engineer would do at a client

At a client, a forward deployed engineer would start from the client's landing zone rather than this repo's defaults. That means their subscription layout, hub network, private DNS, naming standard, tag policy and whichever IaC tool their platform team already runs. The engineer maps these templates onto that: wires the pipeline to the client's GitHub or Azure DevOps organization with OIDC federated credentials scoped per environment, sets required reviewers that match the client's change-approval process, and turns on private endpoints and the client's policy initiatives before any data flows. After a first dev deployment the engineer runs the smoke tests and eval gates with the client's own data owners, agrees the cost profile and budget alerts, and hands over a runbook (deploy, rollback, teardown, on-call signals) so the client's team can operate it without the engineer. For the portfolio the early work would be choosing which one or two projects map to the client's real workflow, then replacing their mock systems of record with the client's sandbox APIs behind the same MCP tool contracts.
