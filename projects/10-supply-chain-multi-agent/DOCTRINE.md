# Doctrine card: Supply-chain replenishment team (supervisor, specialists, critic, human approval)

<!-- GENERATED from doctrine.yaml + evals/scores.json by `python -m shared.doctrine render`. Do not edit by hand. -->

> A supervisor routes a demand agent and an inventory agent in parallel, then a sourcing agent that drafts one purchase order. A deterministic reviewer checks quantity, lead time, vendor choice and the provenance of every number, a buyer approves, and only then does the orchestrator release the PO (idempotently) in the ERP.

| Field | Value |
|---|---|
| Owner | Jagadish Meduri |
| Industry | Manufacturing / distribution (supply chain, procurement) |
| Maturity | **Level 4**: multi-agent write path with per-agent least-privilege MCP identities, deterministic critic, human approval before release, idempotent release with compensation |
| Next rung | move the demand agent behind A2A to a lakehouse-native forecasting agent; supervised auto-release for low-value repeat POs once review pass rate and buyer overrides stay green |
| Graph | `supply_chain.graph:build_graph` |

## Plane dependencies

| Plane | Dependency |
|---|---|
| Experience | buyer approval step (interrupt payload with recommendation, review result and per-number citations); buyer channel notification after release |
| Agent | LangGraph supervisor graph - supervisor (LLM + guards) fans out demand/inventory in parallel (Send), then supplier; reviewer critic; human_approval interrupt; submit_po |
| Knowledge | none at runtime (procurement policy and planning math are deterministic code); supplier quote text is treated as untrusted and sanitised |
| Data | certified semantic model (weekly_units measure), SAP-like ERP (stock, open POs, PO drafts, release, cancel) and supplier portal via MCP, one scoped gateway per agent |

## Systems of record and semantic models

| System | Kind | Contract | Access |
|---|---|---|---|
| Sales semantic model | semantic_model | `analytics.get_measure(weekly_units, sku, week)` | read |
| ERP (SAP-like) | mcp | `erp.get_stock, erp.get_open_purchase_orders (read); erp.create_po_draft, erp.submit_purchase_order, erp.cancel_po_draft (write, idempotent)` | read_write |
| Supplier portal | mcp | `suppliers.list_suppliers, suppliers.get_supplier_quote (read, external text)` | read |

## Knowledge: retrieval corpora and ACL


No retrieval corpus. Numbers flow as typed tool artifacts, never through LLM text, and every number in the recommendation carries the agent/tool that produced it.

## MCP / A2A contracts

- MCP `analytics.get_measure(measure, entity, grain) -> {values}`
- MCP `erp.get_stock(sku) -> Stock`
- MCP `erp.get_open_purchase_orders(sku) -> list[PO]`
- MCP `erp.create_po_draft(po, idempotency_key, dry_run) -> Draft`
- MCP `erp.submit_purchase_order(draft_id, idempotency_key, dry_run) -> PO (ERP dedupes on key)`
- MCP `erp.cancel_po_draft(draft_id, reason, idempotency_key, dry_run) -> Draft`
- MCP `suppliers.list_suppliers(sku) -> list[Supplier]`
- MCP `suppliers.get_supplier_quote(supplier, sku, qty) -> Quote`

Specialist.run is the only interface the supervisor uses, so the demand agent can become an A2A client to a lakehouse agent without touching the graph (not implemented here).

**Tool identities (gateway allowlists):**

| Identity | Allowed tools |
|---|---|
| `mi-demand-planner` | `analytics.get_measure` |
| `mi-inventory-reader` | `erp.get_stock`, `erp.get_open_purchase_orders` |
| `mi-sourcing-drafter` | `suppliers.list_suppliers`, `suppliers.get_supplier_quote`, `erp.create_po_draft` |
| `mi-po-releaser` | `erp.submit_purchase_order`, `erp.cancel_po_draft` |

## Stop conditions

- supervisor turn cap (8) and cost budget (60 LLM + tool calls) -> halted_budget
- reviewer can send the supplier agent back once; a second failure escalates to a buyer
- no agent has a release tool; release happens only in submit_po after human approval
- a system of record down after retries ends the run (deferred) instead of planning on partial data

## Failure playbook (five exits per node)

| Node | Success | Retry (backoff) | Compensate | Degrade | Escalate |
|---|---|---|---|---|---|
| `supervisor` | LLM route accepted by the prerequisite guards | fallback deployment | n/a (routing only) | invalid/unparseable route or models down -> deterministic plan policy; system of record down -> finish as deferred | n/a (budget exhaustion ends the run as halted_budget) |
| `demand_agent` | forecast from the forecast_demand tool (semantic model) | gateway backoff; analytics still down -> deferred to next planning run | n/a (read-only) | agent skipped its tool or model down -> deterministic SMA forecast, provenance flagged guard_fallback | n/a |
| `inventory_agent` | stock, open POs and safety stock from ERP tools | gateway backoff; ERP still down -> deferred to next planning run | n/a (read-only) | agent skipped tools or model down -> direct ERP read through the same scoped gateway | n/a |
| `supplier_agent` | one draft PO with quotes as evidence | gateway backoff on quote/draft calls | n/a (a draft is not sent; cancelled later if release fails) | model down -> deterministic cheapest-acceptable sourcing; injected supplier text neutralised | no acceptable quote or draft failed -> buyer notified (no_supplier) |
| `reviewer` | recommendation passes quantity, lead-time, vendor and citation checks | one revision loop back to supplier_agent with the reviewer's issues | n/a | n/a | fails twice -> buyer (review_failed) |
| `human_approval` | buyer approves | n/a | n/a | n/a | is the human gate; reject -> po_rejected, nothing released |
| `submit_po` | PO released once (idempotency key po-submit:<draft>); replay after a crash returns the same PO | gateway backoff; crash after release -> checkpoint replay is deduped by the ERP | release still failing -> draft cancelled (erp.cancel_po_draft) and buyer notified | n/a | cancel refused (already released) or ERP fully down -> buyer reconciles manually |
| `finalize` | FinalReport with outcome, citations and hop count | n/a | n/a | n/a | n/a |

## Chaos scenarios (asserted in `tests/test_chaos.py`)

| Fault | Node | Expected exit | Invariant |
|---|---|---|---|
| `model` | `supervisor` | **degrade** | deterministic routing + sourcing; same Acme PO released exactly once after approval |
| `sor:erp` | `inventory_agent` | **retry** | ERP down -> run deferred; no draft created, nothing released |
| `sor:erp.submit_purchase_order` | `submit_po` | **compensate** | release fails after approval -> draft cancelled, nothing released, buyer notified |
| `jailbreak` | `supplier_agent` | **degrade** | injected quote text neutralised before any agent/reviewer sees it; PO still reviewed and approved |

## Evaluation

Golden set: `evals/golden.jsonl` · suite: `supply_chain.eval_suite:run_case` · run `python -m evals --project 10`

| Metric | Threshold | Current |
|---|---|---|
| task_success | >=0.9 | 1.00 |
| groundedness | - | n/a |
| policy_violation_rate | <=0 | 0.00 |
| tool_error_rate | - | 0.05 |
| cost_per_task | <=0.003 | $0.00023 |

Cases: 17 · gate: **PASS**

## KPIs

| KPI | Target | How measured |
|---|---|---|
| Planner time per replenishment decision | -60% vs manual three-screen process | time from trigger to buyer decision (interrupt -> resume) |
| Cheapest-acceptable vendor rate | >= 95% of released POs | reviewer pass on vendor rule / buyer overrides |
| Stockouts on agent-planned SKUs | -20% vs prior quarter | stockout days per SKU (inventory gold) |
| Duplicate or unapproved POs | 0 | ERP release log vs approvals (idempotency keys) |

## ROI sketch

Value is planner hours saved, lower unit cost from choosing the cheapest acceptable quote instead of the habitual vendor, and fewer stockouts and expedites. Subtract token cost (small: mostly deterministic tools) and buyer review time. Duplicate-PO and wrong-vendor risk is the main downside, which the reviewer, approval gate and idempotent release exist to remove.
