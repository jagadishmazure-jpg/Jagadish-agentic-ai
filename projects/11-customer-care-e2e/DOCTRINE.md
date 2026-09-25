# Doctrine card: End-to-end customer care - "My shipment is late, can I get a refund?"

<!-- GENERATED from doctrine.yaml + evals/scores.json by `python -m shared.doctrine render`. Do not edit by hand. -->

> The full request path as runnable code. A FastAPI BFF authenticates the channel and tenant and rate-limits. The care graph classifies with a confidence gate and a fraud pre-route, plans lanes and a tool budget, reads the order over MCP, retrieves policy as of the purchase date in parallel with ACL-trimmed CRM case history, and proposes a deterministic refund. A critic repairs the draft once, then escalates. Large or risky refunds go to a specialist with an SLA timer that queues or denies on timeout (never pays). Money moves only through an outbox worker, and the reply is honest when the provider is slow.

| Field | Value |
|---|---|
| Owner | Jagadish Meduri |
| Industry | Retail & logistics (e-commerce customer care) |
| Maturity | **Level 5**: governed autonomy end to end - small policy-true refunds pay without a human, with channel auth, rate limits, budgets, critic, SLA-timed HITL, outbox writes, tracing and a container/deployment path |
| Next rung | move checkpoints and the outbox to durable stores (Postgres / Service Bus), then raise the auto-refund limit only after a quarter of green leakage and second-contact KPIs |
| Graph | `care_e2e.graph:build_graph` |

## Plane dependencies

| Plane | Dependency |
|---|---|
| Experience | FastAPI BFF - bearer-token auth stub, channel claim, tenant header check, token-bucket rate limit per tenant+channel, JSON and SSE streaming endpoints, specialist approval console endpoint, SLA sweep job endpoint; APIM in the Azure sketch |
| Agent | LangGraph care graph (classify -> plan -> order -> [policy || history] -> refund -> critic -> human_approval -> finalize | handoff) with checkpoints and interrupt() |
| Knowledge | care-policy corpus on the shared ContextBuilder - temporal editions retrieved as-of the purchase date, ACL (fraud playbook fraud-ops only), sanitizer; CRM cases turned into ACL/tenant-carrying chunks and trimmed per principal |
| Data | OMS (orders, scans), CRM (verify, account risk flag, case history, notes), payment provider (idempotent refunds) via MCP servers - in-process or streamable-HTTP containers - behind reader/writer gateways; outbox (Service Bus stand-in) |

## Systems of record and semantic models

| System | Kind | Contract | Access |
|---|---|---|---|
| OMS | mcp | `oms.get_order (read); oms.mark_order_refunded (write, idempotent)` | read_write |
| CRM | mcp | `crm.verify_customer, crm.get_account, crm.get_contact_history (read); crm.add_case_note (write)` | read_write |
| Payment provider | mcp | `payments.issue_refund (write; provider dedupes on idempotency key)` | write |
| Refund outbox | event_stream | `outbox command refund:<order> -> worker.dispatch (Service Bus queue with duplicate detection in Azure)` | read_write |

## Knowledge: retrieval corpora and ACL

| Corpus | Owner | ACL | Temporal validity | Refresh SLA | Sensitivity |
|---|---|---|---|---|---|
| care-policy | Jagadish Meduri (care policy product) | CARE-LATE-*, CARE-AUTO-1, CARE-COMMS-1 everyone; CARE-FRAUD-INT fraud-ops only | late-delivery 2025 and 2026 editions (valid_from/valid_to); retrieved as-of the order purchase date | event-driven on policy publish; semantic cache invalidated by corpus version | internal |
| crm-case-history (per request) | Jagadish Meduri (CRM data product) | each case carries groups + tenant; care principal sees care cases of its own tenant only | live read per request (no cache) | real time via crm.get_contact_history | confidential (PII redacted by the sanitizer) |

## MCP / A2A contracts

- MCP `oms.get_order(order_id) -> Order`
- MCP `oms.mark_order_refunded(order_id, refund_id, idempotency_key, dry_run)`
- MCP `crm.verify_customer(customer_id, email) -> {verified}`
- MCP `crm.get_account(account_id) -> {risk_flag, tenant}`
- MCP `crm.get_contact_history(account_id) -> list[Case]`
- MCP `crm.add_case_note(customer_id, note, idempotency_key, dry_run)`
- MCP `payments.issue_refund(order_id, amount, idempotency_key, dry_run)`

Fraud review is a queue handoff today; a fraud domain agent over the shared A2A contract would be the first peer.

**Tool identities (gateway allowlists):**

| Identity | Allowed tools |
|---|---|
| `mi-care-reader` | `oms.get_order`, `crm.verify_customer`, `crm.get_account`, `crm.get_contact_history` |
| `mi-refund-writer` | `payments.issue_refund`, `oms.mark_order_refunded`, `crm.add_case_note` |

## Stop conditions

- confidence below 0.6 -> clarifying question; fraud signal -> specialist handoff before any refund tool is reachable
- planner tool budget (<= 8 calls per request, guarded); exhausted -> escalate
- critic repairs a draft once; a second failure escalates to a specialist with the template reply
- refunds above $50, injected text in case history, missing policy evidence or critic failure stop at a human with a 4-hour SLA; timeout queues or denies and never pays
- only the outbox worker identity can move money; one refund per order (idempotency key refund:<order>)

## Failure playbook (five exits per node)

| Node | Success | Retry (backoff) | Compensate | Degrade | Escalate |
|---|---|---|---|---|---|
| `classify` | intent + confidence from the model, CRM risk flag read | fallback deployment | n/a (read-only) | models down -> keyword classifier; CRM down -> no risk flag, refund forced to HITL | fraud signal -> specialist handoff |
| `plan` | model plan within allowed lanes and budget | fallback deployment | n/a | invalid plan (e.g. no policy lane) or models down -> default plan | n/a |
| `order` | identity verified and order owned by the caller (schema-valid OMS payload) | gateway backoff | n/a (read-only) | order not on this account -> neutral 'check the number' reply (never confirm others' orders) | OMS/CRM down or tool budget exhausted -> case opened, honest reply, nothing changed |
| `policy` | edition in force on the purchase date retrieved with citations | n/a (search is idempotent; one attempt per request) | n/a | search down / no edition -> no auto-refund, specialist approval required, no citation claimed | n/a |
| `history` | ACL- and tenant-trimmed case snippets, sanitised | gateway backoff | n/a | CRM down -> proceed without history | instruction-like text in case history -> specialist approval |
| `refund` | deterministic proposal (edition rules) + model-drafted reply | fallback deployment | n/a (no side effects) | models down -> template reply | n/a |
| `critic` | draft passes money-moved, citation, amount, leakage and injection checks | one repair with the critic's issues | n/a | models down -> template repair | still failing -> template reply + specialist approval |
| `human_approval` | care specialist approves or denies (agents cannot approve) | n/a | n/a | n/a | SLA expired -> queue for review (or deny by config); never pays |
| `finalize` | refund dispatched via outbox and confirmed by the provider | outbox worker redelivers (provider dedupes on the key) | n/a - reply never claims money moved before confirmation | provider slow/down -> command stays queued, reply gives reference CS-<order> | n/a |
| `handoff` | clarify / routed / not-found reply with reference | n/a | n/a | n/a | fraud, other intents, SoR down and budget exhaustion land in the specialist queue |

## Chaos scenarios (asserted in `tests/test_chaos.py`)

| Fault | Node | Expected exit | Invariant |
|---|---|---|---|
| `model` | `classify` | **degrade** | keyword classifier + template drafts; same $48.99 refund paid exactly once |
| `retrieval` | `policy` | **degrade** | no auto refund; paused for specialist approval; nothing paid |
| `sor:oms` | `order` | **escalate** | case opened with honest reply; nothing paid or invented |
| `sor:payments` | `finalize` | **degrade** | refund command queued in the outbox; reply gives a reference and never says issued |
| `jailbreak` | `history` | **escalate** | injected CRM case text neutralised; refund paused for a human; nothing paid |

## Evaluation

Golden set: `evals/golden.jsonl` · suite: `care_e2e.eval_suite:run_case` · run `python -m evals --project 11`

| Metric | Threshold | Current |
|---|---|---|
| task_success | >=0.95 | 1.00 |
| groundedness | >=0.95 | 1.00 |
| policy_violation_rate | <=0 | 0.00 |
| tool_error_rate | - | 0.02 |
| cost_per_task | <=0.002 | $0.00007 |

Cases: 21 · gate: **PASS**

## KPIs

| KPI | Target | How measured |
|---|---|---|
| Late-delivery refund containment | >= 70% closed without a human | threads ending refund_issued/not_eligible/status_update with no agent touch and no second contact in 7 days |
| Refund leakage | 0 refunds outside policy | weekly audit of payments vs proposal + policy edition |
| Honest-status rate | 100% of queued refunds carry a reference and no 'issued' claim | critic + reply scan on refund_queued outcomes |
| HITL SLA | p95 decision < 4 h; 0 silent payments on timeout | interrupt -> resume/sweep timestamps |

## ROI sketch

Late-delivery refund contacts are high volume and repetitive. Containing them saves fully loaded agent time and gives customers a faster, honest answer. The costs are specialist review time for large refunds, token spend (small, since eligibility and amounts are deterministic) and the platform work (BFF, MCP servers, outbox). Leakage is kept at zero by construction because the model never sets amounts. Second contacts are reduced by never claiming a refund moved before the provider confirms it.
