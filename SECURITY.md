# Security policy

## Supported versions

Only the `main` branch is maintained. There are no released versions.

## Reporting a vulnerability

Please do not open a public issue with the details.

1. Use GitHub private vulnerability reporting: **Security** tab -> **Report a vulnerability** on [Jagadish-agentic-ai](https://github.com/jagadishmazure-jpg/Jagadish-agentic-ai/security).
2. If that button is not shown, open an issue titled `Security contact request` with no technical details, and I will reply with a private channel.

I aim to acknowledge a report within 5 working days. This is a personal portfolio maintained by one person, so there is no formal SLA or bug bounty.

## Scope

This repository is a demonstration. It runs offline against mocks and synthetic data and has never been deployed to a live Azure tenant. In scope: anything in the code, infrastructure definitions or workflows that would be unsafe if someone deployed it as written (for example, a role that is broader than documented, a secret that could leak through CI, or a guardrail that can be bypassed). Out of scope: the deterministic mocks and sandbox stand-ins themselves.

## What the repo already does

- No secrets in the repo; CI signs in to Azure with OIDC only ([ADR 0003](docs/adr/0003-oidc-and-managed-identity.md)).
- The portfolio API forces the mock model unless `PORTFOLIO_ALLOW_LIVE=1`, so a deployed instance cannot spend model quota by accident.
- Tool calls go through a gateway with per-identity allow-lists; prompt-injection sanitising on retrieved text; human approval before risky actions.
- checkov scans the Terraform on every change, with each skipped check justified in [`.checkov.yaml`](.checkov.yaml).
- **Prompt injection screening:** offline, every retrieved chunk and tool payload goes through the regex sanitizer (`shared/context/sanitize.py`). Setting `PROMPT_SHIELDS=1` and `AZURE_CONTENT_SAFETY_ENDPOINT` adds Azure AI Content Safety Prompt Shields after it (`shared/context/content_safety.py`): keyless, batched, and fail closed. The Prompt Shields path is unit-tested with a fake transport and has not been run against Azure.
- **Threat model:** [`docs/security/threat-model.md`](docs/security/threat-model.md) maps STRIDE, the OWASP Top 10 for LLM Applications and MITRE ATLAS techniques to this repository's real components, with the control, the test that proves it and whether it is built, written but not deployed, or planned.
- **Supply chain:** every third-party GitHub Action is pinned to a full commit SHA with its version in a comment, and every workflow starts from read-only `permissions`. Dependabot proposes weekly, grouped updates ([`.github/dependabot.yml`](.github/dependabot.yml)); CodeQL scans the Python code and the workflow files ([`codeql.yml`](.github/workflows/codeql.yml)); gitleaks scans the full git history in CI. A test (`test_workflows_are_hardened`) fails if an action is left unpinned or a workflow loses its `permissions` block.
- **SBOM:** the `sbom` job in [`ci.yml`](.github/workflows/ci.yml) builds an SPDX JSON software bill of materials from the lockfiles and manifests on every run and keeps it as the `sbom.spdx.json` build artifact.
- **Container images:** base images are pinned by digest (the tag stays for readability; Dependabot's docker ecosystem moves both), and pip/uv are removed from the runtime layer. The image job in [`infra.yml`](.github/workflows/infra.yml) then (1) runs Trivy `v0.70.0` through `aquasecurity/trivy-action` v0.36.0, pinned to its commit SHA because older trivy-action tags were hijacked in a public supply-chain incident, and fails on any HIGH or CRITICAL finding that has a fix; (2) writes an SPDX image SBOM artifact; and (3) on pushes to `main` only, signs SLSA build provenance for the saved image archive with `actions/attest-build-provenance` (Sigstore keyless signing through GitHub OIDC; no registry, no Azure). The archive is kept as a build artifact for five days so the provenance can be checked: download `image-agentic-portfolio.tar` from the run and run `gh attestation verify image-agentic-portfolio.tar --repo jagadishmazure-jpg/Jagadish-agentic-ai`. CI never pushes these images to a registry.
- **Known scanner false positives** are listed by fingerprint in [`.gitleaksignore`](.gitleaksignore), each with the reason (for example a public Azure built-in role ID); none is a credential.
- **GitHub settings:** secret scanning with push protection, Dependabot alerts and security updates, private vulnerability reporting, and a ruleset on `main` that blocks force-pushes and branch deletion and requires the CI checks before a pull request can merge. The maintainer (repository admin) can still push directly to `main`, so for direct pushes the checks run after the push rather than before it.
- Full status of each control, including known gaps (no SBOM or image signing yet): [`docs/best-practices.md`](docs/best-practices.md).
