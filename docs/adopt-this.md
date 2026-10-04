# Adopt this

How another team reuses the portfolio: what to copy, what to configure, and how to extend it without losing the guarantees the gates give you.

## What you can reuse

| You want | Take | Configure | Doc |
|---|---|---|---|
| A governed agent for one workflow | the closest project folder (see the project table in the root README) | `doctrine.yaml`, golden set, your systems behind MCP | that project's README, section 17 |
| The shared controls only | `shared/` as a package (`pip install -e .` builds `shared`) | identities, allow-lists, budgets, thresholds | [components](components/README.md) |
| Keyless model access | `shared/llm.py` | `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT`, role assignment | [model-factory](components/model-factory.md) |
| A promotion gate for agents | `shared/doctrine/`, `shared/evals/`, `evals/` | your card schema additions and thresholds | [doctrine-gate](components/doctrine-gate.md) |
| Hosting and pipelines | `infra/`, `.github/workflows/` | tfvars, OIDC variables, `DEPLOY_ENABLED` | [infrastructure](components/infrastructure.md) |
| Docs that cannot drift | `scripts/render_docs.py` (generic) | markers in your Markdown | [implementation guide](implementation-guide.md) |

## Reuse a project in five steps

1. **Copy** `projects/NN-name/` to a new folder, rename its package and add both to `pythonpath` and `known-first-party` in `pyproject.toml`.
2. **Replace the mocks**: implement backends with the same method names as the MCP tool contracts and pass them to the `build_*_server` functions, or point `McpConnection` at your MCP server over HTTP.
3. **Rewrite `doctrine.yaml`** for your owner, systems, corpus ACL, stop conditions, KPIs and thresholds. Run `python -m shared.doctrine validate` until it passes.
4. **Replace the golden set** with real, reviewed cases from your domain.
5. **Run the gates** (`pytest`, `python -m evals`, `python -m shared.doctrine validate`, `python scripts/render_docs.py --check`) and wire them into your CI.

## Configure

| Concern | Setting |
|---|---|
| Model provider | `LLM_PROVIDER`, `AZURE_OPENAI_*` (keyless by default) |
| Fallback deployment | `AZURE_OPENAI_FALLBACK_DEPLOYMENT` |
| Tool access | `ToolGateway(allow=..., quotas=..., max_calls=...)` per agent |
| Retrieval budget | `Budget(policy=, facts=, history=, tool_io=)` per agent |
| Quality bar | `eval.thresholds` in `doctrine.yaml` |
| Telemetry | `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_CONSOLE`, price variables |
| Deployment | `DEPLOY_ENABLED`, `DEPLOY_TOOL`, `envs/*.tfvars`, `live_llm` |

## Extend

- **A new node**: add it in `build_graph`, then its five-exit row; the validator fails until the row exists.
- **A new dependency**: put it behind the gateway, add a chaos row and a test in `test_chaos.py`.
- **A new metric**: return it from `run_case`, aggregate it in the harness and add a threshold.
- **A new card field** (for example a privacy assessment reference): add it to `DoctrineCard` in `shared/doctrine/card.py`; every card must then declare it.

## What you still have to do yourself

- Replace synthetic data and mock systems with real ones, and re-run evals on a live model before trusting wording.
- Measure the KPIs in production; the targets in the cards are design targets.
- Create the Azure prerequisites (app registration, federated credentials, environments with reviewers).
