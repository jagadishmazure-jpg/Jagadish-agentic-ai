# Doctrine card: Telecom outage-aware care - topology blast radius, fresh truth, no upsell in outages

<!-- GENERATED from doctrine.yaml + evals/scores.json by `python -m shared.doctrine render`. Do not edit by hand. -->

> Customer care that knows the network. Outage truth comes from the OSS over MCP with a freshness check: a stale feed is disclosed ("our status data is 50 minutes old"), never presented as fact. A redundancy-aware service topology graph decides whether an incident actually reaches the customer's access node (a dual-homed cell survives a single aggregation failure). Bills are explained line by line with tariff citations retrieved as of the bill period. Offers are blocked during a confirmed or unverifiable outage. When no outage explains a failed line test, a field dispatch context pack is created. A NOC assistant, on a read-only identity, summarises incidents and what-if blast radius and never acts.

| Field | Value |
|---|---|
| Owner | Jagadish Meduri |
| Industry | Telecommunications (broadband and mobile care, NOC) |
| Maturity | **Level 4**: autonomous for read-and-explain journeys and truck-roll creation, with guards (freshness, no upsell in outage, citations) and a summarise-only NOC mode |
| Next rung | subscribe to OSS alarms on Event Hubs to push proactive outage notices, and add outage credits as an outbox write once credit accuracy is proven |
| Graph | `outage_care.graph:build_graph` |

## Plane dependencies

| Plane | Dependency |
|---|---|
| Experience | care app/chat (customer channel) and NOC console (summarise-only channel) |
| Agent | LangGraph care graph (intake -> [status || account] -> triage -> bill_explain | dispatch | offers -> respond) and noc_summary branch; guards in respond and noc_summary |
| Knowledge | tariff corpus (plan editions as-of the bill period, proration, equipment, outage credits; NOC runbook ACL noc only) on the shared ContextBuilder; service topology graph for blast radius |
| Data | OSS, billing, diagnostics, offer engine and field service via MCP; care reader, field writer and read-only NOC identities |

## Systems of record and semantic models

| System | Kind | Contract | Access |
|---|---|---|---|
| OSS / fault management | mcp | `oss.get_active_incidents() -> incidents + observed_at (freshness SLA 15 min)` | read |
| Billing | mcp | `billing.get_bill(account) -> period_start, lines` | read |
| Line diagnostics | api | `diagnostics.line_test(account) -> ont, signal_dbm` | read |
| Offer engine | api | `offers.get_offers(account)` | read |
| Field service | mcp | `field.create_dispatch(pack, idempotency_key, dry_run)` | write |

## Knowledge: retrieval corpora and ACL

| Corpus | Owner | ACL | Temporal validity | Refresh SLA | Sensitivity |
|---|---|---|---|---|---|
| tariffs | Jagadish Meduri (product pricing) | care and noc; NOC-RUNBOOK-INT noc only | plan tariffs by edition (2025, 2026); retrieved as-of the bill period start | on tariff publication | internal |

The service topology (depends_on with dual-homing) is a graph knowledge source computed deterministically, not retrieved by similarity.

## MCP / A2A contracts

- MCP `oss.get_active_incidents()`
- MCP `billing.get_bill(account)`
- MCP `diagnostics.line_test(account)`
- MCP `offers.get_offers(account)`
- MCP `field.create_dispatch(pack, idempotency_key, dry_run)`

A NOC incident agent could publish incident summaries to care over the shared A2A contract.

**Tool identities (gateway allowlists):**

| Identity | Allowed tools |
|---|---|
| `mi-care-reader` | `oss.get_active_incidents`, `billing.get_bill`, `diagnostics.line_test`, `offers.get_offers` |
| `mi-field-writer` | `field.create_dispatch` |
| `mi-noc-reader` | `oss.get_active_incidents` |

## Stop conditions

- OSS feed older than 15 minutes or unavailable -> status "unknown", disclosed; no dispatch, no offers
- confirmed outage on the customer's path -> ETA answer, no offers, no truck roll
- dispatch only when the status is fresh, no incident covers the path and the line test fails (one per account per day)
- bill lines are explained only with retrieved tariff citations; unexplained lines are flagged for follow-up
- the NOC assistant refuses action requests and strips action language; its identity has no write tools

## Failure playbook (five exits per node)

| Node | Success | Retry (backoff) | Compensate | Degrade | Escalate |
|---|---|---|---|---|---|
| `intake` | intent from the model (outage, billing, other) or NOC channel routing | fallback deployment | n/a | models down -> keyword intent | n/a |
| `status` | fresh OSS incidents + topology decide confirmed / none | gateway backoff | n/a (read-only) | stale feed or OSS down -> unknown, disclosed to the customer | n/a |
| `account` | bill and line test read | gateway backoff | n/a (read-only) | billing or diagnostics down -> continue without that input | n/a |
| `triage` | next step chosen (bill explain, dispatch, offers) | n/a | n/a | n/a | status unknown and line down -> no truck roll, agent follows up |
| `bill_explain` | every line tied to a tariff retrieved as of the bill period | n/a (idempotent search) | n/a | tariffs unavailable -> lines listed, flagged for follow-up; injected bill text neutralised | n/a |
| `dispatch` | field dispatch with context pack (path, equipment, diagnostics, incidents, safety) | gateway backoff; idempotency key dispatch:<account>:<date> | cancel dispatch in field service (no-access or self-resolved) | field service down -> no booking, honest answer | n/a |
| `offers` | offers only when no outage and not a service complaint | gateway backoff | n/a | offer engine down -> no offers | n/a |
| `respond` | model answer passing upsell, freshness and citation guards | fallback deployment | n/a | models down or guard failure -> template | n/a |
| `noc_summary` | incidents and blast radius (current state + what-if) summarised | fallback deployment | n/a | models down or action language -> template summary; OSS down -> no summary | action requested -> refused (summarise-only) |

## Chaos scenarios (asserted in `tests/test_chaos.py`)

| Fault | Node | Expected exit | Invariant |
|---|---|---|---|
| `model` | `intake` | **degrade** | keyword intent + template; confirmed outage and ETA still stated |
| `sor:oss` | `status` | **degrade** | status unknown disclosed; no dispatch; no offers |
| `retrieval` | `bill_explain` | **degrade** | no tariff citations claimed; lines flagged for follow-up |
| `jailbreak` | `bill_explain` | **degrade** | injected bill text neutralised; never echoed |

## Evaluation

Golden set: `evals/golden.jsonl` · suite: `outage_care.eval_suite:run_case` · run `python -m evals --project 16`

| Metric | Threshold | Current |
|---|---|---|
| task_success | >=0.95 | 1.00 |
| groundedness | >=0.95 | 1.00 |
| policy_violation_rate | <=0 | 0.00 |
| tool_error_rate | - | 0.04 |
| cost_per_task | <=0.002 | $0.00004 |

Cases: 19 · gate: **PASS**

## KPIs

| KPI | Target | How measured |
|---|---|---|
| Avoidable truck rolls | 0 dispatches while a confirmed or unverifiable outage covers the path | field dispatches vs OSS incidents on the service path |
| Upsell during outage | 0 offers shown | offer impressions for accounts on a confirmed-outage path |
| Stale-status disclosure | 100% of answers on a stale feed say so | respond guard + reply scan |
| Bill-explain contact containment | >= 60% resolved without an agent | billing intents without transfer or repeat contact in 7 days |

## ROI sketch

During outages, care queues spike with the same question, and customers who are told "restart your router" or offered an upgrade get angrier. Grounding answers in live OSS truth and topology deflects those contacts with an honest ETA, avoids truck rolls that the network fault already explains, and protects NPS by suppressing offers. Cited bill explanations reduce billing escalations. Costs are OSS/billing integration and model usage; the NOC assistant saves engineer time on incident summaries without any change authority.
