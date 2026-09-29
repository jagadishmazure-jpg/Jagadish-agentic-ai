# ADR 0002: Run offline against deterministic mocks by default

- **Status:** Accepted
- **Date:** 2026-09-29

## Context

Reviewers need to clone the repo and see it work in minutes, without an Azure subscription, model quota or vendor sandbox accounts. Tests that call real models are slow, cost money and give different answers on each run, which makes eval gates flaky.

## Decision

Every external dependency has a deterministic offline stand-in (a deterministic `MockChatModel`, mock systems of record behind MCP servers and synthetic corpora), and offline mode is the default. The Azure code paths are written against the real SDK signatures and switched on explicitly (`LLM_PROVIDER` or Azure OpenAI / OpenAI settings in `.env`; the portfolio API also needs `PORTFOLIO_ALLOW_LIVE=1`).

## Consequences

- Tests and eval gates are fast and repeatable, so a regression is a real regression.
- Scores measure the orchestration, retrieval, policy and scoring logic, not the quality of a real model. Every README says so.
- The Azure code paths are not exercised by CI. They stay unverified until a subscription exists, and the docs say that plainly.
- Stand-ins must be clearly labelled so nobody mistakes them for vendor products or real data.
