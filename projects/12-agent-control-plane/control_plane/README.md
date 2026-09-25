# `control_plane/`: registry, caller policy and governed A2A mesh

The importable package for project 12: a governed agent mesh. Every agent registers a card
(purpose, skills with side-effect class, owner, allowed callers, budgets, eval scores).
The control plane decides on every A2A task whether the caller may call that callee for that
tenant, and enforces a kill switch and an eval-score promotion gate. A LangGraph journey agent
asks "can we promise this B2B order?" by fanning out to CRM, SAP-like and demand agents over
A2A in one trace, and drafts a PO only when policy allows it.

| File | What it does |
|---|---|
| [`__init__.py`](__init__.py) | Package docstring. |
| [`agents.py`](agents.py) | Peer agents behind A2A, each with its own MCP identity: `crm-agent` (read-only customer 360), `sap-agent` (stock, open POs, PO drafts: reversible write), `demand-agent` (forecast over the semantic model, reusing project 10's logic), plus the journey agent's own registration. `build_network()` returns the `Network` (control plane, one A2A app per peer, gateways); `default_policy`, `card_for`, `records`. |
| [`api.py`](api.py) | `create_app()`: FastAPI registry API (`GET/POST /registry/agents`, `/promote`, `/kill`, `/revive`, `GET /registry/audit`; admin routes require an `X-Admin-Token` header) plus every peer's A2A endpoint under `/agents/{name}/`. |
| [`demo.py`](demo.py) | CLI behind `run.py`: parallel fan-out in one trace, shortfall PO draft (allowed for tenant `northwind` only), governance refusals (unregistered caller, marketing agent write, schema rejection), kill switch and promotion gate; `--mermaid PATH`. |
| [`eval_suite.py`](eval_suite.py) | `run`, `run_case`, `chaos_scenario` and `CHAOS_CHECKS`. |
| [`journey.py`](journey.py) | Journey agent `build_graph()`: `intake` (model parse with `regex_parse` fallback) -> `discover` (registry and cards) -> `crm` / `sap` / `demand` over A2A (Send fan-out) -> `decide` (deterministic ATP) -> `draft_po` (idempotent A2A write, only on shortfall for customers in good standing) -> `respond`. |
| [`plane.py`](plane.py) | `ControlPlane.authorize` and `Rule`. Checks in order, first failure wins, every decision audited: registration (caller and callee), kill switch, prod stage, tenant entitlement, allowed callers, per-tenant skill/side-effect rules, budget. |
| [`registry.py`](registry.py) | `Registry`, `AgentRecord`, `Budgets`, `RegistryError`. Unregistered agents cannot call or be called; new registrations start in `dev`; promotion to `prod` is gated on eval scores per side-effect class. |

## Flow

```
journey: intake -> discover -> [crm || sap || demand] (A2A, one traceparent) -> decide -> draft_po? -> respond
each A2A call: peer app guard -> ControlPlane.authorize(caller, callee, tenant, skill) -> schema -> handler
```

## Run the HTTP surface

```bash
PYTHONPATH=.:projects/12-agent-control-plane:projects/10-supply-chain-multi-agent \
  uvicorn control_plane.api:app --factory --port 8081
curl localhost:8081/agents/sap-agent/.well-known/agent.json
```

## Design notes

- Policy is enforced at the callee's A2A server, not by caller goodwill.
- A killed peer is skipped by discovery and the journey degrades honestly instead of guessing.
- Uses the shared A2A contract in [`shared/a2a`](../../../shared/a2a/README.md).

## Run

```bash
python projects/12-agent-control-plane/run.py                    # demo (offline, mock LLM)
python projects/12-agent-control-plane/run.py --mermaid projects/12-agent-control-plane/graph.mmd  # also refresh the Mermaid diagram
pytest projects/12-agent-control-plane                           # tests
python -m evals --project 12                # golden-set eval
CHAOS_FAULTS=model python projects/12-agent-control-plane/run.py   # demo with every model deployment down
```

See the [project README](../README.md) for the business problem and design trade-offs, and [`DOCTRINE.md`](../DOCTRINE.md) for the five-exit table per node.
