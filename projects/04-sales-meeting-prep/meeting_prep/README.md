# `meeting_prep/`: parallel research brief with Send fan-out

The importable package for project 04. Before a customer meeting it researches CRM history,
open deals, support tickets and news in parallel (one LangGraph `Send` per source), merges the
results with reducers and writes a one-page brief whose every bullet cites a source id. A
failing source becomes a gap in the brief rather than a failed run; below a quorum of sources
the brief is marked insufficient.

| File | What it does |
|---|---|
| [`__init__.py`](__init__.py) | Package docstring. |
| [`demo.py`](demo.py) | CLI behind `run.py`; `--fail news` (or another source) simulates an outage, `--mermaid PATH`. |
| [`eval_suite.py`](eval_suite.py) | `run_case`, `chaos_scenario` and `CHAOS_CHECKS`. |
| [`graph.py`](graph.py) | `build_graph()`, the `PrepState` with merge reducers, `ResearchTask` and `Brief`. Nodes: `plan`, `research` (one branch per source), `synthesize`, `render_brief`. |
| [`llm.py`](llm.py) | Synthesiser prompt and a deterministic mock that writes cited talking points and risks. |
| [`sor.py`](sor.py) | CRM (interactions, deals) and support desk (tickets) behind MCP with a read-only gateway (`mi-meeting-prep`); payload contracts `Interaction`, `Deal`, `Ticket`. News stays a direct fetcher. |
| [`sources.py`](sources.py) | Mock research sources with stable citable ids (`CRM-2`, `NEWS-1`, ...) and per-source injectable failures and latency; `seed_sources()`. |

## Graph

```
plan --Send x N--> research(source)   (all branches in one super-step)
     reducers merge findings / errors / timings --> synthesize --> render_brief
```

## Design notes

- Transient errors are retried once; non-transient errors are not (see tests).
- Uncited or invented bullets are dropped by the synthesiser guard.
- With every model deployment down, the synthesiser degrades to rule-based cited bullets.
- A neutralised injected instruction in a tool payload is recorded as a `research -> degrade` exit.

## Run

```bash
python projects/04-sales-meeting-prep/run.py                    # demo (offline, mock LLM)
python projects/04-sales-meeting-prep/run.py --mermaid projects/04-sales-meeting-prep/graph.mmd  # also refresh the Mermaid diagram
pytest projects/04-sales-meeting-prep                           # tests
python -m evals --project 04                # golden-set eval
CHAOS_FAULTS=model python projects/04-sales-meeting-prep/run.py   # demo with every model deployment down
```

See the [project README](../README.md) for the business problem and design trade-offs, and [`DOCTRINE.md`](../DOCTRINE.md) for the five-exit table per node.
