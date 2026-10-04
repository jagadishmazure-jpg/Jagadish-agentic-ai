# Implementation guide

How the portfolio is built, in the order you would build it again, with the commands that prove each step. Everything runs offline against the deterministic mock model.

## 1. Environment

```bash
uv sync --locked --all-extras --group dev   # Python 3.11+, from uv.lock
export LLM_PROVIDER=mock                     # the default anyway; explicit in CI
```

## 2. The shared platform first

Build the cross-cutting pieces once in `shared/`, then keep projects focused on business logic.

| Order | Component | Doc | Proof |
|---|---|---|---|
| 1 | Model factory, keyless Azure auth | [model-factory](components/model-factory.md) | `pytest shared/tests/test_llm.py` |
| 2 | Resilience, faults, chaos | [resilience-and-chaos](components/resilience-and-chaos.md) | `pytest shared/tests/test_resilience.py` |
| 3 | Tracing and cost | [observability](components/observability.md) | `pytest shared/tests/test_observability.py` |
| 4 | Knowledge plane | [context-builder](components/context-builder.md) | `pytest shared/tests/test_context.py` |
| 5 | MCP servers and tool gateway | [mcp-servers](components/mcp-servers.md), [tool-gateway](components/tool-gateway.md) | `pytest shared/tests/test_mcp_gateway.py shared/tests/test_mcp_http.py` |
| 6 | A2A contract | [a2a](components/a2a.md) | `pytest shared/tests/test_a2a.py` |
| 7 | Eval harness | [eval-harness](components/eval-harness.md) | `python -m evals --no-write` |
| 8 | Doctrine cards and gate | [doctrine-gate](components/doctrine-gate.md) | `python -m shared.doctrine validate` |
| 9 | Portfolio API | [portfolio-api](components/portfolio-api.md) | `pytest shared/tests/test_api.py` |
| 10 | Infrastructure and pipelines | [infrastructure](components/infrastructure.md) | `terraform -chdir=infra/terraform test` |

## 3. A project, step by step

Every project under `projects/NN-name/` follows the same recipe. Project 03 (refund agent) is the reference.

1. **Write the business problem and the graph first.** Decide where the model adds value (language in, language out) and keep money, policy and routing in plain Python over typed state.
2. **Model state and outputs** with a `TypedDict` for graph state and Pydantic models for anything that crosses a boundary.
3. **Put systems of record behind MCP tools** (`shared/mcp_servers`) and reach them only through a `ToolGateway` with one identity and an allow-list.
4. **Retrieve through `ContextBuilder`** with the caller's principal and the as-of date that matters for the decision.
5. **Wrap the model with `get_resilient_llm(mock_responder=...)`** and write a deterministic responder so tests and evals are repeatable.
6. **Write `doctrine.yaml`**: planes, systems, corpus and ACL, contracts, identities, stop conditions, a five-exit row for every node, chaos scenarios, eval thresholds, KPIs, maturity and ROI.
7. **Write tests** (`tests/`), including `test_chaos.py` with one test per chaos row.
8. **Write the golden set** (`evals/golden.jsonl`, at least ten cases) and `run_case` in `eval_suite.py`.
9. **Render and gate:**

```bash
pytest projects/03-refund-agent
python -m evals --project 03
python -m shared.doctrine render && python -m shared.doctrine validate
python scripts/render_docs.py          # paste real output and excerpts into the README
```

10. **Write the README in the 17 standard sections.** Sections that come from the card (steps, playbook, chaos, thresholds, identities, Azure mapping) are pasted by `scripts/doc_tables.py`, so they cannot drift from `doctrine.yaml`.

## 4. Keeping docs honest

| Marker | Filled by | Checked in CI |
|---|---|---|
| `<!-- output: command -->` | stdout of the command (offline, ids masked) | `python scripts/render_docs.py --check` |
| `<!-- output-md: python scripts/doc_tables.py NN section -->` | Markdown generated from `doctrine.yaml` | same |
| `<!-- code: path::name -->` | current source of a function, class or method | same |

`shared/tests/test_repo_docs.py` checks the structure: every project README and component doc has the 17 sections in order, every folder has a README, guides exist and no placeholders remain.

## 5. Optional: a real model

```bash
az login
export AZURE_OPENAI_ENDPOINT=https://<resource>.openai.azure.com/ AZURE_OPENAI_DEPLOYMENT=<deployment>
python projects/03-refund-agent/run.py          # keyless through DefaultAzureCredential
python -m evals --project 03 --live --no-write  # same golden set, real model
```

Your identity needs the Cognitive Services OpenAI User role on the resource. No key is required.

## 6. Optional: deploy

Follow [deployment.md](deployment.md). The pipeline stays off until the repository variable `DEPLOY_ENABLED` is `true`; nothing has been deployed.
