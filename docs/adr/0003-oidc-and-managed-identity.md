# ADR 0003: Use OIDC federation for CI and managed identities at runtime

- **Status:** Accepted (not yet exercised)

## Context

A deploy pipeline needs to sign in to Azure, and the deployed workloads need to reach Azure services. Client secrets and storage keys in GitHub or in app settings can leak, expire and are hard to rotate.

## Decision

GitHub Actions signs in with `azure/login` using OpenID Connect and a federated credential on an Entra app registration, one subject per GitHub Environment (`dev`, `prod`); no client secret is stored. Workloads run as user-assigned managed identities with role assignments scoped to the resources they use (AcrPull, plus Cognitive Services OpenAI User when a live model is enabled; the app's own model calls are keyless too: `shared/llm.py` uses `DefaultAzureCredential` with a bearer-token provider and falls back to an API key only when one is set). Terraform uses `ARM_USE_OIDC` and Entra ID auth for the state backend.

## Consequences

- No secret to rotate or leak in CI; access can be cut by deleting the federated credential.
- The one-time setup (app registration, federated credentials, role assignments, state storage) has to be done by someone with rights in the tenant. It is written out step by step in `docs/deployment.md` but has not been done, because there is no subscription yet.
- Local development still needs a way to authenticate (`az login` / `DefaultAzureCredential`) when running in Azure mode.
