# `shared/doctrine/`: doctrine cards and the promotion gate

Every project carries a machine-checked `doctrine.yaml`. This package defines its schema,
validates it as a promotion gate and renders it to the project's `DOCTRINE.md` and to the
compliance matrix in the top-level README. A card has to name the project's plane
dependencies, systems of record, retrieval corpus and ACL, MCP/A2A contracts, stop conditions,
a five-exit row for every graph node, chaos scenarios, an eval set with thresholds and passing
scores, an owner, KPIs, a maturity level and an ROI sketch.

| File | What it does |
|---|---|
| [`__init__.py`](__init__.py) | Re-exports `DoctrineCard`, `ChaosScenario`, `load_card`, `project_dirs`, `validate_project` and `render_card`. |
| [`__main__.py`](__main__.py) | CLI: `python -m shared.doctrine validate | render | matrix [--project NN]`. `validate` exits non-zero on any problem, including a stale `DOCTRINE.md` or README matrix; `render` rewrites them. |
| [`card.py`](card.py) | Pydantic schema (`DoctrineCard`, `Kpi`, `SystemOfRecord`, `Corpus`, `Knowledge`, `Contracts`, `Identity`, `ChaosScenario`, `EvalSpec`, `Maturity`), `load_card`, `project_dirs`, `graph_nodes` (reads the compiled graph to check five-exit coverage), `validate_project`, `render_card`, `render_matrix` and `readme_with_matrix`. |

## Usage

```bash
python -m shared.doctrine validate               # promotion gate for every project (CI step)
python -m shared.doctrine validate --project 03
python -m shared.doctrine render                 # regenerate projects/*/DOCTRINE.md + README matrix
python -m shared.doctrine matrix                 # print the compliance matrix
```

`validate` checks: card completeness, a five-exit row for every node in the compiled graph,
at least 10 golden cases, a `scores.json` that meets the card's thresholds, and that the
generated markdown is up to date. Run `python -m evals` first if scores changed, then `render`.

The generated files (`DOCTRINE.md` and the block between the `doctrine-matrix` markers in the
root README) should not be edited by hand.
