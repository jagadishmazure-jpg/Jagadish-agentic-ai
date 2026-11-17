# Assessment bank

A small FastAPI app for the Full Stack Agentic AI course. Each module has a YAML question bank and a pytest lab. Quizzes are graded from the answer key on the server. Labs run the learner's `solution.py` against the checked-in tests.

Modules, in course order: Foundations, Frameworks & Orchestration, LLM Core, RAG Stack, Agentic Core, Trust & Quality, Customization, Production & Deployment.

Sign-in is a mock bearer token locally (`Authorization: Bearer ada`). A deployment sets `ASSESSMENT_AUTH_MODE=entra` and checks an Entra External ID (CIAM) access token. Progress sits in memory locally. A deployment sets `ASSESSMENT_STORE=cosmos`.

The lab runner is a subprocess with a timeout in a temporary directory. It is not a security sandbox. A real course deployment should grade inside a fresh container.

## What a live Azure subscription has to provide

CI does not call Azure. To run the deployed path you need:

- A subscription and permission to `terraform apply` or `bicep` the resource group.
- An **Entra External ID** tenant. Apply the Terraform with the azuread provider pointed at that tenant so the app registration is created there. Bicep does not create the registration; pass the tenant id, subdomain and client id into `infra/bicep/main.bicep`.
- A pushed container image (`assessment-bank/Dockerfile`) and `container_image` set to it.
- Learners signing in against `https://<subdomain>.ciamlogin.com/<tenant>/v2.0` and calling the API with the resulting bearer token.
- The container's managed identity can write the Cosmos container. The account has local keys disabled.

## Run locally

```bash
PYTHONPATH=assessment-bank uvicorn assessment_bank.app:create_app --factory --port 8080
curl -s localhost:8080/healthz
curl -s localhost:8080/modules -H 'authorization: Bearer ada'
```

Answers are not in `GET /modules/{id}`. Submit them to `POST /modules/{id}/quiz`. Submit lab source to `POST /modules/{id}/labs/{lab_id}` as `{"code": "..."}`. `GET /progress` is per learner.

## Layout

| File | What it does |
|---|---|
| [`Dockerfile`](Dockerfile) | API image. Mock auth and memory store unless the env overrides them. |
| [`assessment_bank/`](assessment_bank/README.md) | FastAPI app, bank loader, grader, auth, stores. |
| [`banks/`](banks/README.md) | One YAML file per module. Answer keys live here and are not returned by the API. |
| [`labs/`](labs/README.md) | Pytest modules the grader runs against a submission. Not collected by the portfolio suite. |
| [`infra/`](infra/README.md) | Terraform and Bicep for Container Apps, Cosmos DB and the External ID settings. |
| [`tests/`](tests/README.md) | API, grading, token and IaC parity tests. |

## Live environment

| Variable | Role |
|---|---|
| `ASSESSMENT_AUTH_MODE` | `mock` (default) or `entra` |
| `ENTRA_TENANT_ID` | External ID tenant id |
| `ENTRA_CLIENT_ID` | Application id, also the token audience |
| `ENTRA_TENANT_SUBDOMAIN` | Host label for `https://<subdomain>.ciamlogin.com` |
| `ENTRA_AUTHORITY` | Issuer. Derived from the subdomain and tenant when omitted |
| `ENTRA_JWKS_URL` | Optional override. Default is the CIAM discovery keys URL |
| `ASSESSMENT_STORE` | `memory` (default) or `cosmos` |
| `COSMOS_ENDPOINT` | Account endpoint |
| `COSMOS_DATABASE` | `assessments` |
| `COSMOS_CONTAINER` | `progress` (partition key `/learnerId`) |
