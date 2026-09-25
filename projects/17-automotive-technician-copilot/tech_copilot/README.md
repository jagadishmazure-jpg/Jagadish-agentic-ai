# `tech_copilot/`: service-bay TSB, wiring and warranty copilot

The importable package for project 17. The VIN is decoded over MCP; technical service bulletins
(TSBs) are retrieved as of the repair date with applicability checks, and a superseded bulletin
is dropped whenever its successor is valid, even if the old record was never retired. Wiring
diagrams are indexed by caption. A safety check allows torque specs and part numbers only from
current TSBs, parts availability comes from an ATP tool with part supersession, and a covered
warranty claim always waits for an administrator before it is submitted idempotently.

| File | What it does |
|---|---|
| [`__init__.py`](__init__.py) | Empty package marker. |
| [`demo.py`](demo.py) | CLI behind `run.py`: current TSB with the right torque and part and a warranty claim after approval, the same car with an earlier repair date, a wrong-version model corrected by the safety check, a build-date filter excluding a TSB, and the agent refused when it tries to approve its own claim; `--mermaid PATH`. |
| [`eval_suite.py`](eval_suite.py) | `run`, `violations`, `run_case`, `chaos_scenario` and `CHAOS_CHECKS`. |
| [`graph.py`](graph.py) | `build_graph()` and `TechState`. Nodes: `intake`, `tsb`, `diagrams`, `procedure`, `parts`, `warranty`, `warranty_approval` (interrupt), `finalize`. Also `stale_responder`, a model that remembers the old spec, used to prove the safety check. |
| [`knowledge.py`](knowledge.py) | TSB and wiring-diagram corpus on `shared.context` with issue-date validity, the applicability registry (`Applies`, `applies()`: model, years, engine, build-date window) and `current_only()` supersession filter. |
| [`sor.py`](sor.py) | MCP servers (vehicle, parts, warranty) and gateways (reader, warranty writer). |
| [`systems.py`](systems.py) | Mock VIN decode, parts ATP with part supersession and warranty programs; `seed_systems()`. |

## Graph

```
intake (VIN decode via MCP, concern sanitised)
  -> [tsb (as-of repair date, applicability, supersession) || diagrams (caption-indexed, applicability)]
  -> procedure (model guidance + safety check) -> parts (ATP, part supersession)
  -> warranty (coverage tool) -> warranty_approval (always HITL when covered) -> finalize
```

## Design notes

- Specs are checked, not prose: torque values and part numbers in the guidance are compared
  with the current bulletin, and a mismatch replaces the guidance with the bulletin text.
- Only administrators can approve; customer-pay jobs create no claim and no interrupt.

## Run

```bash
python projects/17-automotive-technician-copilot/run.py                    # demo (offline, mock LLM)
python projects/17-automotive-technician-copilot/run.py --mermaid projects/17-automotive-technician-copilot/graph.mmd  # also refresh the Mermaid diagram
pytest projects/17-automotive-technician-copilot                           # tests
python -m evals --project 17                # golden-set eval
CHAOS_FAULTS=model python projects/17-automotive-technician-copilot/run.py   # demo with every model deployment down
```

See the [project README](../README.md) for the business problem and design trade-offs, and [`DOCTRINE.md`](../DOCTRINE.md) for the five-exit table per node.
