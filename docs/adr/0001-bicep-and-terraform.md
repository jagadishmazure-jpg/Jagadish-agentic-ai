# ADR 0001: Keep Bicep and add a Terraform twin

- **Status:** Accepted
- **Date:** 2026-09-29

## Context

The infrastructure was first written in Bicep (`infra/bicep/main.bicep`). Clients who hire for Azure agent work often already run Terraform, with a platform team, a module registry and a plan review in every pull request. Others are Azure-only and prefer Bicep, where ARM is the source of truth and there is no state file to secure.

## Decision

Keep the Bicep and add a Terraform version of the same resources (`infra/terraform`) using `azurerm` (plus `azapi` only where `azurerm` has no resource yet). Terraform uses Cloud Adoption Framework names, a fixed tag set, dev and prod tfvars, a partial `azurerm` backend with Entra ID auth, and offline `terraform test` runs against mocked providers. The deploy workflow takes a `deploy_tool` input so either stack can be used.

## Consequences

- Every infrastructure change has to be made twice, or the difference has to be written down in the Terraform README. The differences that exist today (names, tags, extra hardening) are listed there.
- One environment must be owned by one tool. The pipeline keeps separate resource groups per environment, and the README warns against pointing both tools at the same group.
- CI checks both: `bicep build` with no warnings, and `terraform fmt`, `validate`, `test`, tflint and checkov.
- Terraform needs remote state; the one-time bootstrap is documented and the state account has shared keys turned off.
