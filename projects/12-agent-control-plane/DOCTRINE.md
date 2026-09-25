# Doctrine card: Agent control plane - registry, A2A contract and who-may-call-whom policy

<!-- GENERATED from doctrine.yaml + evals/scores.json by `python -m shared.doctrine render`. Do not edit by hand. -->

> A governed agent mesh. Every agent registers a card (purpose, skills with side-effect class, tools, models, budgets, owner, allowed callers, tenants, eval scores) and must be promoted through an eval-score gate before anyone can call it. Agents talk over an A2A-shaped task contract (agent card at /.well-known/agent.json, JSON-RPC message/send) that carries the tenant, the calling agent and a W3C traceparent. The control plane checks every task at the callee: registration, kill switch, stage, tenant, allowed callers, per-tenant skill policy, schema and budget. The demo journey agent asks CRM, SAP-like and Databricks-like demand agents in parallel whether an order can be promised, and drafts a PO on a shortfall.

| Field | Value |
|---|---|
| Owner | Jagadish Meduri |
| Industry | Cross-industry platform (B2B manufacturing / distribution demo) |
| Maturity | **Level 4**: multi-agent with enforced contracts - registry, promotion gate, per-tenant policy, kill switch, budgets and end-to-end tracing across agents; the one write is a reversible PO draft |
| Next rung | back the registry with a store and signed agent cards (Entra agent identities), push policy to APIM so it is enforced at the edge as well, and feed eval scores from CI automatically |
| Graph | `control_plane.journey:build_graph` |

## Plane dependencies

| Plane | Dependency |
|---|---|
| Experience | registry admin API (FastAPI; platform-admin token stub) and each peer's A2A endpoint mounted under /agents/<name>; account managers use the journey agent from their CRM |
| Agent | LangGraph journey agent (intake -> discover -> [crm || sap || demand] -> decide -> draft_po -> respond) calling peer agents over A2A; peers are thin skills over their own MCP gateways |
| Knowledge | none - the journey answers from live system data only; agent cards are the discovery metadata |
| Data | CRM, ERP (SAP-like stock, open POs, PO drafts) and a Databricks-like analytics measure via MCP servers, each behind the owning agent's gateway identity |

## Systems of record and semantic models

| System | Kind | Contract | Access |
|---|---|---|---|
| CRM | mcp | `crm.get_account (read) - via crm-agent only` | read |
| ERP (SAP-like) | mcp | `erp.get_stock, erp.get_open_purchase_orders (read); erp.create_po_draft (write, idempotent) - via sap-agent only` | read_write |
| Lakehouse gold (Databricks-like) | semantic_model | `analytics.get_measure(weekly_units, sku) - via demand-agent only` | read |
| Agent registry | api | `GET/POST /registry/agents, /promote, /kill, /revive, /audit` | read_write |

## Knowledge: retrieval corpora and ACL


No retrieval corpus by design - every number in the answer comes from a peer agent's system-of-record read, and the journey's reply is checked against the deterministic ATP.

## MCP / A2A contracts

- MCP `crm.get_account(account_id) -> {customer_id, tenant, credit_hold, notes}`
- MCP `erp.get_stock(sku) / erp.get_open_purchase_orders(sku)`
- MCP `erp.create_po_draft(po, idempotency_key, dry_run)`
- MCP `analytics.get_measure(measure, entity, grain)`
- A2A `crm-agent.get_customer_360 {customer_id} -> customer_360 (read_only)`
- A2A `sap-agent.get_stock {sku} -> stock (read_only)`
- A2A `sap-agent.create_po_draft {sku, qty, reason, idempotency_key} -> po_draft (reversible_write; tenant northwind only)`
- A2A `demand-agent.forecast {sku, weeks} -> forecast (read_only; project 10 forecasting logic)`

A2A-shaped JSON-RPC (message/send, tasks/get) with agent card at /.well-known/agent.json; headers x-tenant-id, x-caller-agent, traceparent. Error codes: -32602 schema, -32010 policy, -32011 kill switch, -32012 budget, -32004 unavailable.

**Tool identities (gateway allowlists):**

| Identity | Allowed tools |
|---|---|
| `mi-crm-agent` | `crm.get_account` |
| `mi-sap-agent` | `erp.get_stock`, `erp.get_open_purchase_orders`, `erp.create_po_draft` |
| `mi-demand-agent` | `analytics.get_measure` |
| `journey-agent (A2A caller)` | `crm-agent.get_customer_360`, `sap-agent.get_stock`, `sap-agent.create_po_draft (northwind)`, `demand-agent.forecast` |

## Stop conditions

- every A2A task is authorised at the callee; the first failed check rejects it with a coded error and an audit record
- killed or unpromoted peers are skipped at discovery; missing inputs mean "cannot confirm", never a promise
- credit hold or customer not visible in the tenant -> escalate to a human, no promise
- at most one PO draft per thread and SKU (idempotency key po:<thread>:<sku>); drafts only, a buyer releases
- per caller+tenant call budget on each peer (-32012 when exhausted)

## Failure playbook (five exits per node)

| Node | Success | Retry (backoff) | Compensate | Degrade | Escalate |
|---|---|---|---|---|---|
| `intake` | model parses customer, SKU, qty and horizon | fallback deployment | n/a (read-only) | models down or bad JSON -> regex parser | request not understood -> ask for the standard phrasing |
| `discover` | all three peers registered, enabled and in prod | n/a | n/a | killed / unpromoted peer skipped; its data reported as unavailable | n/a |
| `crm` | customer 360 from crm-agent in the caller's tenant | peer gateway backoff inside crm-agent | n/a (read-only) | peer unreachable or its CRM down -> no customer data, no promise; injected note text arrives neutralised | control-plane rejection (policy, budget) -> reason surfaced |
| `sap` | on hand, safety stock and open PO quantity from sap-agent | peer gateway backoff inside sap-agent | n/a (read-only) | peer unreachable or ERP down -> stock unavailable, no promise | control-plane rejection -> reason surfaced |
| `demand` | forecast over the horizon from demand-agent (project 10 logic) | peer gateway backoff inside demand-agent | n/a (read-only) | peer unreachable -> forecast unavailable, no promise | control-plane rejection (e.g. policy rule removed) -> reason surfaced |
| `decide` | deterministic ATP = on hand + open POs - forecast - safety stock | n/a | n/a | any input missing -> "cannot confirm", planner follow-up | credit hold or customer not in tenant -> human (finance / account owner) |
| `draft_po` | PO draft for the shortfall rounded up to 50, via sap-agent, idempotent | A2A replay with the same idempotency key is safe | erp.cancel_po_draft (draft only, nothing released) | sap-agent unreachable -> reply says a buyer must raise the PO | policy denies drafts in this tenant -> buyer raises the PO |
| `respond` | model wording whose numbers match the decision | fallback deployment | n/a | models down or numbers mismatch -> template reply | n/a |

## Chaos scenarios (asserted in `tests/test_chaos.py`)

| Fault | Node | Expected exit | Invariant |
|---|---|---|---|
| `model` | `intake` | **degrade** | regex intake + template reply; same promise with ATP 360 |
| `a2a:sap-agent` | `sap` | **degrade** | stock unavailable -> cannot confirm; never says YES |
| `sor:crm` | `crm` | **degrade** | crm-agent's system down -> no customer data -> cannot confirm; no PO drafted |
| `jailbreak` | `crm` | **degrade** | instruction planted in CRM notes neutralised by crm-agent's sanitizer; promise still computed from data |

## Evaluation

Golden set: `evals/golden.jsonl` · suite: `control_plane.eval_suite:run_case` · run `python -m evals --project 12`

| Metric | Threshold | Current |
|---|---|---|
| task_success | >=0.95 | 1.00 |
| groundedness | - | n/a |
| policy_violation_rate | <=0 | 0.00 |
| tool_error_rate | - | 0.02 |
| cost_per_task | <=0.002 | $0.00004 |

Cases: 14 · gate: **PASS**

## KPIs

| KPI | Target | How measured |
|---|---|---|
| Unregistered or unauthorised A2A calls served | 0 | audit log: allow decisions without a matching registry record + rule |
| Kill-switch time to effect | next task (no redeploy) | kill event -> first rejected task timestamp |
| Agents in prod below their promotion bar | 0 | registry scan of stage=prod vs PROMOTION_BARS |
| Cross-agent trace completeness | >= 99% of A2A tasks share the caller trace id | a2a.server spans with a parent from the caller |

## ROI sketch

The value is avoided risk and faster reuse rather than a single workflow saving. Teams can call each other's agents without bespoke integration because the contract and the policy are shared. Security and risk reviews approve one control plane instead of every pair of agents. A bad release can be switched off in seconds without a redeploy, and every cross-agent answer can be traced end to end. Costs are the platform team and a registry/policy store.
