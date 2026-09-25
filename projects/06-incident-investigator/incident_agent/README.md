# `incident_agent/`: autonomous ReAct incident investigator

The importable package for project 06. On an alert, an autonomous ReAct agent (LangChain
`create_agent`) reads metrics, deploy history, logs and runbooks, then writes a root-cause
report in which every claim cites an observed evidence id. Hard stop conditions (steps, tool
cost, loop detection) are enforced as agent middleware, and the only write action, a rollback,
pauses the graph with `interrupt()` until a human approves it.

| File | What it does |
|---|---|
| [`__init__.py`](__init__.py) | Package docstring. |
| [`demo.py`](demo.py) | CLI behind `run.py`: runs the two incident scenarios and prints the tool trace; `--reject` declines the rollback, `--mermaid PATH`. |
| [`eval_suite.py`](eval_suite.py) | `run`, `run_case`, `chaos_scenario` and `CHAOS_CHECKS`. |
| [`graph.py`](graph.py) | Outer graph `open_case -> investigator -> write_report` and `build_graph(systems)`. `RootCauseReport` / `ReportDraft` schemas, `IncidentState`, and `ModelOutageMiddleware`, which turns "all deployments down" into a clean stop with the evidence gathered so far. |
| [`guards.py`](guards.py) | `GuardrailMiddleware`: `max_steps` (default 8 model turns), `max_tool_cost` (default 20 cost units) and loop detection (an identical tool call is not executed; after `max_loop_hits` such attempts the agent stops). |
| [`knowledge.py`](knowledge.py) | SRE runbooks on `shared.context`: DBA failover runbooks are ACL-restricted to `dba`, and RB-DB-07 has a superseded 2025 edition so lookups follow the incident date. `lookup()`. |
| [`llm.py`](llm.py) | Investigator system prompt and `mock_investigator`, a deterministic ReAct policy used offline. |
| [`sor.py`](sor.py) | Ops MCP server (`OpsBackend`): logs, metrics and deploy history are reads; `rollback_deploy` is the only write (idempotency key, dry-run by default). `build_gateway()`. |
| [`systems.py`](systems.py) | Mock observability stack and deploy system for two scenarios: `checkout-api` (error spike after deploy v2.14.0, DB pool exhausted) and `search-api` (latency, upstream Elasticsearch timeouts, no deploy). `seed_systems()`. |
| [`tools.py`](tools.py) | `make_tools()`: investigation tools. Every result carries an evidence id (`EV-<tool>-<hash>`) that the report must cite; `propose_rollback` calls `interrupt()`. |

## Flow

```
open_case -> investigator (ReAct loop + GuardrailMiddleware + ModelOutageMiddleware;
                           propose_rollback -> interrupt() for approval)
          -> write_report (schema + evidence validation)
```

## Design notes

- **Evidence ids**: the report is rejected (and sent to a human) if it cites evidence that was
  never observed.
- **Stops are code, not prompt text**: step, cost and loop limits live in middleware.
- A failed or degraded observation is still returned to the agent as a tool message, so it
  sees the gap, and is recorded as a degrade exit.

## Run

```bash
python projects/06-incident-investigator/run.py                    # demo (offline, mock LLM)
python projects/06-incident-investigator/run.py --mermaid projects/06-incident-investigator/graph.mmd  # also refresh the Mermaid diagram
pytest projects/06-incident-investigator                           # tests
python -m evals --project 06                # golden-set eval
CHAOS_FAULTS=model python projects/06-incident-investigator/run.py   # demo with every model deployment down
```

See the [project README](../README.md) for the business problem and design trade-offs, and [`DOCTRINE.md`](../DOCTRINE.md) for the five-exit table per node.
