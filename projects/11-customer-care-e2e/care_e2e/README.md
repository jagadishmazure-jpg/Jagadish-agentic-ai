# `care_e2e/`: end-to-end late-shipment refund journey

The importable package for project 11: the full request path for a customer asking for a refund
on a late shipment, as runnable code. A FastAPI backend-for-frontend (BFF) authenticates the channel
and tenant, rate-limits and streams progress over SSE. Behind it, a LangGraph care graph
classifies, plans, reads OMS/CRM over MCP, retrieves policy as of the purchase date, proposes
a refund with deterministic rules, checks the reply with a critic, waits for a specialist on
large amounts (with an SLA timer) and writes through an outbox that a worker drains.

| File | What it does |
|---|---|
| [`__init__.py`](__init__.py) | Package docstring. |
| [`bff.py`](bff.py) | Experience plane. `create_app()` with a bearer-token auth stub (identity from claims, never the body), channel-claim and `X-Tenant-Id` checks, a per (tenant, channel) `TokenBucket` returning 429, and routes `POST /v1/channels/{channel}/messages`, `.../messages/stream` (SSE), `POST /v1/approvals/{thread_id}` (HITL resume) and `POST /v1/ops/sla-sweep`. |
| [`critic.py`](critic.py) | `check(draft, facts)`: deterministic checks before anything reaches the customer: no claim that money moved before the provider confirmed, no internal fraud/risk language, no instruction-like text, the policy citation present and the exact approved amount (no other amounts). |
| [`demo.py`](demo.py) | CLI behind `run.py`: a $48.99 auto refund over SSE, a $249 refund approved via the console endpoint, payments down then worker redelivery, and a fraud pre-route plus a vague message; `--mermaid PATH`. |
| [`eval_suite.py`](eval_suite.py) | `run`, `grounded`, `run_case`, `chaos_scenario` and `CHAOS_CHECKS`. |
| [`graph.py`](graph.py) | `build_graph()` and `sweep_expired()` (SLA timer: resumes overdue approvals with a timeout decision). Nodes: `classify`, `plan`, `order`, `policy`, `history`, `refund`, `critic`, `human_approval`, `finalize`, `handoff`. |
| [`knowledge.py`](knowledge.py) | Care policy corpus on `shared.context`: 2025 and 2026 late-delivery editions retrieved as of the purchase date; the fraud playbook is ACL-restricted to `fraud-ops`; CRM cases become per-request chunks with their own ACL groups and tenant (`case_chunks`). |
| [`llm.py`](llm.py) | Model operations `classify`, `plan`, `draft`, `repair`, each returning `(value, degraded)` with a deterministic fallback; `mock_responder` plus test responders (`sloppy_responder`, `stubborn_responder`) that misbehave on purpose. |
| [`mcp_main.py`](mcp_main.py) | Runs one system of record as a standalone MCP server over streamable HTTP: `python -m care_e2e.mcp_main oms --port 8000` (used by docker-compose). |
| [`policy.py`](policy.py) | Deterministic refund rules per policy edition: `decide()` returns the proposal from order facts and the edition in force on the purchase date; the model only words it. |
| [`sor.py`](sor.py) | OMS, CRM and payments behind the shared MCP domain servers; two identities, `mi-care-reader` (graph reads) and `mi-refund-writer` (outbox worker, the only identity that moves money). `build_gateways()` uses in-process servers or `CARE_MCP_URLS` for remote ones. |
| [`state.py`](state.py) | `CareRequest` and the typed `CareState`. |
| [`systems.py`](systems.py) | Mock OMS (orders and carrier scans), CRM (customers and case timeline with ACL groups and tenant), `Payments` (idempotent on key, optionally slow), the transactional `Outbox`, approval queue helpers and `seed_systems()`. |
| [`worker.py`](worker.py) | Outbox worker: `dispatch` (at-least-once; the provider dedupes on the idempotency key) and `drain` (redeliver queued commands). A slow or down provider leaves the command queued. |

## Graph

```
classify (confidence gate + fraud pre-route) -> plan (lanes + tool budget) -> order (OMS/CRM via MCP)
  -> [policy (RAG as-of purchase date) || history (CRM cases, ACL-trimmed)]
  -> refund (deterministic proposal + drafted reply) -> critic (repair once, then escalate)
  -> human_approval (interrupt, SLA timer; deny/queue on timeout) -> finalize (outbox write)
non-refund routes -> handoff
```

## Design notes

- **HITL with an SLA**: an approval that times out is denied or queued by policy, never paid.
  The agent identity cannot approve its own refund.
- **Outbox writes**: the graph records a command; only the worker, under the writer identity,
  calls payments. A provider outage yields an honest "queued, reference CS-..." reply.
- **Run the BFF** locally with
  `PYTHONPATH=.:projects/11-customer-care-e2e uvicorn care_e2e.bff:app --factory --port 8080`,
  or the full topology with
  `docker compose -f projects/11-customer-care-e2e/docker-compose.yml up --build`.
- Azure mapping (not deployed): [`../deploy/azure`](../deploy/azure/README.md).

## Run

```bash
python projects/11-customer-care-e2e/run.py                    # demo (offline, mock LLM)
python projects/11-customer-care-e2e/run.py --mermaid projects/11-customer-care-e2e/graph.mmd  # also refresh the Mermaid diagram
pytest projects/11-customer-care-e2e                           # tests
python -m evals --project 11                # golden-set eval
CHAOS_FAULTS=model python projects/11-customer-care-e2e/run.py   # demo with every model deployment down
```

See the [project README](../README.md) for the business problem and design trade-offs, and [`DOCTRINE.md`](../DOCTRINE.md) for the five-exit table per node.
