# Security policy

## Supported versions

Only the `main` branch is maintained. There are no released versions.

## Reporting a vulnerability

Please do not open a public issue with the details.

1. Use GitHub private vulnerability reporting: **Security** tab -> **Report a vulnerability** on [Jagadish-agentic-ai](https://github.com/jagadishmazure-jpg/Jagadish-agentic-ai/security).
2. If that button is not shown (private reporting is not switched on for this repo yet), open an issue titled `Security contact request` with no technical details, and I will reply with a private channel.

I aim to acknowledge a report within 5 working days. This is a personal portfolio maintained by one person, so there is no formal SLA or bug bounty.

## Scope

This repository is a demonstration. It runs offline against mocks and synthetic data and has never been deployed to a live Azure tenant. In scope: anything in the code, infrastructure definitions or workflows that would be unsafe if someone deployed it as written (for example, a role that is broader than documented, a secret that could leak through CI, or a guardrail that can be bypassed). Out of scope: the deterministic mocks and sandbox stand-ins themselves.

## What the repo already does

- No secrets in the repo; CI signs in to Azure with OIDC only ([ADR 0003](docs/adr/0003-oidc-and-managed-identity.md)).
- The portfolio API forces the mock model unless `PORTFOLIO_ALLOW_LIVE=1`, so a deployed instance cannot spend model quota by accident.
- Tool calls go through a gateway with per-identity allow-lists; prompt-injection sanitising on retrieved text; human approval before risky actions.
- checkov scans the Terraform on every change, with each skipped check justified in [`.checkov.yaml`](.checkov.yaml).
- Full status of each control, including known gaps (API-key model auth, no CI secret scanner): [`docs/best-practices.md`](docs/best-practices.md).
