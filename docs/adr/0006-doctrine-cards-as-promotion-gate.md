# ADR 0006: Doctrine cards are a promotion gate

- **Status:** Accepted
- **Date:** 2026-09-29

## Context

Twenty-one projects written quickly can drift into demos: no owner, no stop conditions, no failure handling, no eval set. Checking that by hand does not scale.

## Decision

Every project carries a machine-checked `doctrine.yaml` (plane dependencies, systems of record, corpus and ACL, tool contracts, stop conditions, a five-exit row per graph node, eval set, owner, KPI). `python -m shared.doctrine validate` fails CI if anything is missing or scores regress, and the README compliance matrix is generated from the cards.

## Consequences

- Docs cannot drift from the cards: a stale `DOCTRINE.md` or README matrix fails CI.
- Adding a node means adding its failure row, which slows small changes a little.
- The cards describe intent; the chaos tests are what prove the declared exits are taken.
