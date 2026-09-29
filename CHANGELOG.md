# Changelog

Notable changes, newest first. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). There are no versioned releases, so entries are grouped by date.

## Unreleased

### Added

- `docs/best-practices.md`: cloud and agentic AI practices with honest status and links.
- Architecture decision records in `docs/adr/`.
- `SECURITY.md`, `CONTRIBUTING.md` and this changelog.

### Changed

- README sections follow one order: what, why, architecture, run, test, deploy, limits.

## 2026-09-29

### Added

- Portfolio API (`shared/api`, FastAPI) with 5 tests, a root `Dockerfile`, Terraform for Azure Container Apps (`infra/terraform`) and a Bicep twin (`infra/bicep`).
- GitHub Actions `infra.yml`, `deploy.yml` (dev -> prod, Bicep or Terraform, OIDC, gated by `DEPLOY_ENABLED`) and `teardown.yml`; `docs/deployment.md`.
- Project 21: eight multi-agent orchestration patterns on one underwriting task, with a test-enforced comparison.
- Recruiter summary in the README.

## 2026-09-25

### Added

- Projects 01-20, each with typed state, mock services, tests, golden evals, chaos tests and a doctrine card.
- Shared platform: resilience primitives, OpenTelemetry tracing and cost meter, context builder, MCP servers and tool gateway, A2A contract, eval harness, doctrine promotion gate.
- CI with lint, tests, eval gate and doctrine gate; folder READMEs.
