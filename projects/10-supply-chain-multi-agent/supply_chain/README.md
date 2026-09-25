# `supply_chain/`: supervisor multi-agent replenishment

The importable package for project 10. A supervisor routes specialist agents: demand and
inventory run in parallel via `Send`, then a supplier agent sources quotes. A deterministic
reviewer (critic) checks the recommendation and can send it back to the supplier agent once;
a passing recommendation waits for a buyer at `interrupt()` before the orchestrator submits
the purchase order. Each specialist is a LangChain tool-calling agent with its own scoped MCP
gateway, and numbers flow through typed tool artifacts, not model text.

| File | What it does |
|---|---|
| [`__init__.py`](__init__.py) | Package docstring. |
| [`agents.py`](agents.py) | Specialists (`Specialist`, `AgentRun`, `build_specialists`): each is a `create_agent` tool-calling agent with its own prompt and tools. `Specialist.run` is the only interface the graph uses, so a specialist can be swapped for a remote (A2A) agent. Mock policies `mock_demand`, `mock_inventory`, `mock_supplier` (the last one favours the preferred supplier, like an imperfect model). |
| [`demo.py`](demo.py) | CLI behind `run.py`: the four mock scenarios (reorder with approval, no reorder, fallback supplier, reviewer loop) plus a rejection, printing the agent-hop trace; `--sku`, `--mermaid PATH`. |
| [`eval_suite.py`](eval_suite.py) | `run`, `run_case`, `chaos_scenario` and `CHAOS_CHECKS`. |
| [`graph.py`](graph.py) | `build_graph()` and `default_llms()`. Nodes: `supervisor`, `demand_agent`, `inventory_agent`, `supplier_agent`, `reviewer`, `human_approval` (interrupt), `submit_po`, `finalize`. |
| [`policy.py`](policy.py) | Procurement policy constants and pure planning math: `need_qty` (forecast minus on hand and open POs plus safety stock), `acceptable_quotes`, `best_quote`. |
| [`reviewer.py`](reviewer.py) | Critic: deterministic `review()` of the supplier recommendation. |
| [`services.py`](services.py) | Mock enterprise systems: `SalesWarehouse` (lakehouse / demand stand-in), `Erp` (SAP-like stock, open POs, drafts, submit), `SupplierNetwork` (quote API), `Notifier`, and `seed_services()` with four deterministic scenarios. |
| [`sor.py`](sor.py) | Systems of record behind MCP with one scoped gateway per agent: `analytics` (certified `weekly_units` measure), `erp`, `suppliers`. Only the orchestrator identity can release or cancel a PO. `build_gateways()`. |
| [`state.py`](state.py) | `RouteDecision` (supervisor structured output), `Recommendation`, `FinalReport`, the `merge_dicts` reducer and `SupplyChainState`. |
| [`supervisor.py`](supervisor.py) | `decide()`: the model proposes the next hop as structured output, `validate()` checks it against state, and `plan_next()` is the deterministic fallback when the proposal is invalid or unparseable. |
| [`tools.py`](tools.py) | Per-agent tool factories (`demand_tools`, `inventory_tools`, `supplier_tools`), each closing over one gateway. Tools return `(summary_for_llm, artifact)`; an outage returns an `unavailable` artifact so the graph decides the exit. There is deliberately no submit tool. |

## Graph

```
START -> supervisor --(Send, parallel)--> demand_agent | inventory_agent -> supervisor
         supervisor --> supplier_agent -> supervisor
         supervisor --FINISH--> reviewer --pass--> human_approval (interrupt) --> submit_po
                                         --fail (once)--> supplier_agent
         no reorder / sourcing failed / budget exhausted / rejected --> finalize -> END
```

## Design notes

- Guards on the supervisor: iteration cap, cost budget, prerequisite checks and a fallback
  routing policy, so a confused model cannot loop or skip steps.
- Submission is a graph node behind human approval, not a tool the model can call.
- Submit is idempotent after a crash (see `test_idempotent_submit_after_crash`).

## Run

```bash
python projects/10-supply-chain-multi-agent/run.py                    # demo (offline, mock LLM)
python projects/10-supply-chain-multi-agent/run.py --mermaid projects/10-supply-chain-multi-agent/graph.mmd  # also refresh the Mermaid diagram
pytest projects/10-supply-chain-multi-agent                           # tests
python -m evals --project 10                # golden-set eval
CHAOS_FAULTS=model python projects/10-supply-chain-multi-agent/run.py   # demo with every model deployment down
```

See the [project README](../README.md) for the business problem and design trade-offs, and [`DOCTRINE.md`](../DOCTRINE.md) for the five-exit table per node.
