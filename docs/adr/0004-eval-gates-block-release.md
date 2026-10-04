# ADR 0004: Eval gates block the build

- **Status:** Accepted

## Context

Agent behaviour changes when prompts, retrieval, tools or models change, and unit tests do not catch a drop in answer quality or a safety rule that stops holding.

## Decision

Golden eval sets with thresholds run in CI on every push and pull request (one golden set per project with thresholds in its `doctrine.yaml`, plus the doctrine promotion gate; `python -m evals --no-write`). A score below its threshold fails the build, and CI runs the gate without rewriting the checked-in scores, so a regression cannot silently update the baseline.

## Consequences

- Quality and safety regressions are caught before merge, in the same place as lint and tests.
- Golden sets are small and synthetic. Passing them shows the gates work; it does not predict real-world accuracy.
- Changing a threshold is a reviewed code change, not a runtime setting.
