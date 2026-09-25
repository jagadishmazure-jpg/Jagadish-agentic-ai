# `outage_care/`: outage-aware care and read-only NOC summaries

The importable package for project 16. Customer care that knows the network: outage status
comes from the OSS over MCP with a freshness check, and a redundancy-aware topology decides
whether the customer's path is really affected (a dual-homed site survives a single failure).
The graph then explains a bill with tariff citations for the bill period's edition, dispatches
a technician with a context pack, or shows offers, which are blocked during an outage. A
separate NOC branch uses a read-only identity and only summarises.

| File | What it does |
|---|---|
| [`__init__.py`](__init__.py) | Empty package marker. |
| [`demo.py`](demo.py) | CLI behind `run.py`: confirmed outage with ETA and no upsell, a dual-homed customer not affected, ONT offline leading to a dispatch, a bill explained with tariff citations, a stale OSS feed disclosed without a truck roll, and NOC summary / what-if / refused action; `--mermaid PATH`. |
| [`eval_suite.py`](eval_suite.py) | `run`, `run_case`, `chaos_scenario`, `CHAOS_CHECKS` and `pushy_responder` (a model that upsells and suggests actions regardless, used to prove the guards). |
| [`graph.py`](graph.py) | `build_graph()` and `CareState`. Nodes: `intake`, `status`, `account`, `triage`, `bill_explain`, `dispatch`, `offers`, `respond`, `noc_summary`. |
| [`knowledge.py`](knowledge.py) | Tariff corpus on `shared.context` (plan editions as of the bill period, proration, equipment, outage credits) and the NOC runbook (ACL: `noc` only). |
| [`sor.py`](sor.py) | MCP servers (OSS, billing, diagnostics, offers, field service) and identities: `mi-care-reader`, `mi-field-writer` (idempotent dispatch) and `mi-noc-reader` (active incidents only). |
| [`systems.py`](systems.py) | Mock OSS (incidents with observation time), billing, diagnostics, offers and field service; `seed_systems()`. |
| [`topology.py`](topology.py) | Service topology and redundancy-aware `blast_radius(dead)`: a node with several upstreams stays up while any upstream is up. Also `down_set`, `path` (for dispatch context packs) and `affected`. |

## Graph

```
customer: intake -> [status (OSS truth + freshness + topology) || account (bill + line test)]
  -> triage -> bill_explain (tariff RAG) | dispatch (context pack) | offers (blocked in outage)
  -> respond (guards: no upsell in outage, stale data disclosed, citations)
noc:      intake -> noc_summary (read-only identity; summarises, never acts)
```

## Design notes

- A stale OSS feed is disclosed rather than asserted, and no truck is rolled while an outage
  is confirmed or cannot be ruled out.
- Dispatch is idempotent per day.

## Run

```bash
python projects/16-telecom-outage-care/run.py                    # demo (offline, mock LLM)
python projects/16-telecom-outage-care/run.py --mermaid projects/16-telecom-outage-care/graph.mmd  # also refresh the Mermaid diagram
pytest projects/16-telecom-outage-care                           # tests
python -m evals --project 16                # golden-set eval
CHAOS_FAULTS=model python projects/16-telecom-outage-care/run.py   # demo with every model deployment down
```

See the [project README](../README.md) for the business problem and design trade-offs, and [`DOCTRINE.md`](../DOCTRINE.md) for the five-exit table per node.
