# Changelog

Notable changes, newest first. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). There are no versioned releases, so entries are grouped by milestone, newest first.

## Unreleased

### Added

- Private networking option in Terraform and Bicep (`private_networking` / `privateNetworking`, default `false`; on in `prod.tfvars`): VNet with one NSG on both subnets, private endpoints and DNS zones for Foundry and Key Vault, public access off on both (Foundry was hard-coded public), VNet-integrated Container Apps environment. Azure Monitor alerting (on by default): action group, 3 metric and 3 KQL alert rules, diagnostic settings from Foundry, Key Vault and ACR. Opt-in Defender for Cloud plans (`enable_defender = false`). New Bicep modules under `infra/bicep/modules/`, a `private_networking_and_defender` plan test and two parity tests in `shared/tests/test_infra.py`; not deployed.
- Opt-in Azure AI Content Safety Prompt Shields screen (`shared/context/content_safety.py`): with `PROMPT_SHIELDS=1` and `AZURE_CONTENT_SAFETY_ENDPOINT`, sanitised context evidence and tool payloads are also screened, keyless and fail closed. Offline the regex sanitizer remains the only screen. 5 tests with a fake transport; not run against Azure.
- Project 19 Azure fine-tuning script is keyless: `DefaultAzureCredential` with a bearer-token provider for the data plane and an ARM token for `--deploy`; no API key or management token is read from the environment, the dry run documents scopes and roles, and three new tests cover it.
- Threat model (`docs/security/threat-model.md`): STRIDE, OWASP Top 10 for LLM Applications and MITRE ATLAS mapped to this repository's components, each row with its control, test evidence and built / planned status.
- SBOM job in CI: an SPDX JSON software bill of materials of the source tree on every run (artifact `sbom.spdx.json`).
- Container supply chain: base images pinned by digest, pip/uv removed from runtime images, a Trivy image scan that fails on fixable HIGH/CRITICAL findings, an image SBOM, and keyless build provenance for the image archive on `main` (`actions/attest-build-provenance`; verification steps in `SECURITY.md`).
- Supply-chain hardening: every GitHub Action pinned to a commit SHA, top-level `permissions` on `ci.yml`, a gitleaks job in CI, a CodeQL workflow, `.github/dependabot.yml` and a guard test (`test_workflows_are_hardened`).
- GitHub settings: secret scanning and push protection, Dependabot alerts and security updates, private vulnerability reporting and a `main` ruleset.
- `docs/best-practices.md`: cloud and agentic AI practices with honest status and links.
- Architecture decision records in `docs/adr/`.
- `SECURITY.md`, `CONTRIBUTING.md` and this changelog.

### Changed

- README sections follow one order: what, why, architecture, run, test, deploy, limits.

## Milestone 2

### Added

- Portfolio API (`shared/api`, FastAPI) with 5 tests, a root `Dockerfile`, Terraform for Azure Container Apps (`infra/terraform`) and a Bicep twin (`infra/bicep`).
- GitHub Actions `infra.yml`, `deploy.yml` (dev -> prod, Bicep or Terraform, OIDC, gated by `DEPLOY_ENABLED`) and `teardown.yml`; `docs/deployment.md`.
- Project 21: eight multi-agent orchestration patterns on one underwriting task, with a test-enforced comparison.
- Recruiter summary in the README.

## Milestone 1

### Added

- Projects 01-20, each with typed state, mock services, tests, golden evals, chaos tests and a doctrine card.
- Shared platform: resilience primitives, OpenTelemetry tracing and cost meter, context builder, MCP servers and tool gateway, A2A contract, eval harness, doctrine promotion gate.
- CI with lint, tests, eval gate and doctrine gate; folder READMEs.
