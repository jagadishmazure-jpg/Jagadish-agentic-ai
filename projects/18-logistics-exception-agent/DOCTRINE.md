# Doctrine card: Logistics exception agent - event-driven slips, TMS-grounded tracking, no interpolation

<!-- GENERATED from doctrine.yaml + evals/scores.json by `python -m shared.doctrine render`. Do not edit by hand. -->

> An event-driven exception agent. A consumer on the milestone stream (Event Hubs stand-in with partitions, a consumer group and checkpoints) triggers the graph once per slipped milestone. Malformed events go to a dead-letter list, and replays never trigger twice. Tracking answers come only from TMS scan events and cite event IDs. If scans stop, the agent states the last confirmed scan and refuses to estimate the location. A proactive customer notice is drafted only when the slip is confirmed by a high-confidence event and scans are current. Carrier damage claims are built from OCR'd documents: low OCR confidence, or a POD exception missing from TMS, sends the packet to a claims queue. Filing windows come from the carrier rule edition in force on the ship date. A network what-if goes over A2A to a demand/capacity agent.

| Field | Value |
|---|---|
| Owner | Jagadish Meduri |
| Industry | Logistics (freight forwarding, 3PL customer operations) |
| Maturity | **Level 3**: autonomous for grounded tracking answers; customer notices and claims are drafts for CS and claims specialists; low-confidence cases are queued |
| Next rung | auto-send notices for EDI-confirmed slips after a period of draft/sent agreement, and let the capacity agent book reroutes through a guarded write skill |
| Graph | `exception_agent.graph:build_graph` |

## Plane dependencies

| Plane | Dependency |
|---|---|
| Experience | customer portal / chat (tracking, notices) and exception-desk console (slips, claims queue) |
| Agent | LangGraph graph (intake -> track | [evidence || whatif (A2A)] -> comms | ocr -> claim -> respond) triggered by a milestone-stream consumer or a customer request |
| Knowledge | carrier claim rules by tariff edition (temporal) and the proactive-communication policy on the shared ContextBuilder; tracking facts only from TMS events |
| Data | TMS, comms and claims via MCP; milestone event stream; OCR model; capacity agent over A2A |

## Systems of record and semantic models

| System | Kind | Contract | Access |
|---|---|---|---|
| Milestone stream (Event Hubs) | event_stream | `MilestoneEvent {shipment_id, tenant, milestone, planned_at, actual_at, status, source, confidence}` | read |
| TMS | mcp | `tms.get_shipment(shipment_id, tenant); tms.get_scan_events(shipment_id)` | read |
| Customer comms | mcp | `comms.draft_notice(notice, idempotency_key, dry_run)` | write |
| Carrier claims | mcp | `claims.create_claim_draft(claim, idempotency_key, dry_run); claims.queue_review(item, idempotency_key, dry_run)` | write |
| Freight document OCR | document_store | `analyze(content) -> fields {value, confidence}` | read |

## Knowledge: retrieval corpora and ACL

| Corpus | Owner | ACL | Temporal validity | Refresh SLA | Sensitivity |
|---|---|---|---|---|---|
| claim-rules | Jagadish Meduri (carrier management) | logistics-ops | carrier rule edition valid on the ship date (e.g. Ridgeline 2025: 180 days, 2026: 120 days) | on carrier tariff publication | internal |
| comms-policy | Jagadish Meduri (customer operations) | logistics-ops | policy edition by year | on policy change | internal |

Shipment location and status are never retrieved from documents; they come only from TMS scan events and are cited by event ID.

## MCP / A2A contracts

- MCP `tms.get_shipment(shipment_id, tenant)`
- MCP `tms.get_scan_events(shipment_id)`
- MCP `comms.draft_notice(notice, idempotency_key, dry_run)`
- MCP `claims.create_claim_draft(claim, idempotency_key, dry_run)`
- MCP `claims.queue_review(item, idempotency_key, dry_run)`
- A2A `capacity-agent network_whatif {shipment_id, lane, delay_hours} -> whatif {lane_load_pct, options[capacity_ok, recovers_delay]}`

Same A2A contract as project 12 (agent card at /.well-known/agent.json, JSON-RPC message/send, traceparent + X-Tenant-Id); the capacity agent rejects unregistered callers and tenants.

**Tool identities (gateway allowlists):**

| Identity | Allowed tools |
|---|---|
| `mi-exception-reader` | `tms.get_shipment`, `tms.get_scan_events` |
| `mi-comms-writer` | `comms.draft_notice` |
| `mi-claims-writer` | `claims.create_claim_draft`, `claims.queue_review` |

## Stop conditions

- no scans for more than 6 hours on an undelivered shipment -> last confirmed scan only, no location estimate, carrier trace
- track answers cite TMS event IDs; locations, speculation or cites not from TMS events -> template
- inferred or low-confidence (< 0.9) milestone events, or stale scans -> no customer notice, exception desk
- notices never speculate on cause, never name locations and use only the TMS ETA
- low OCR confidence, missing TMS POD exception or passed filing window -> claims queue, no claim draft
- one trigger per (shipment, milestone); malformed events dead-lettered

## Failure playbook (five exits per node)

| Node | Success | Retry (backoff) | Compensate | Degrade | Escalate |
|---|---|---|---|---|---|
| `intake` | shipment loaded for the tenant and routed by request kind | gateway backoff | n/a (read-only) | TMS down -> honest 'unavailable', no guess; instruction-like question neutralised | n/a |
| `track` | answer grounded on TMS scan events with event-ID citations | fallback deployment | n/a | model down or grounding-guard failure -> template from the latest event; injected remark neutralised | scan gap > 6 h -> no interpolation, carrier trace |
| `evidence` | event confidence and scan freshness assessed | gateway backoff | n/a (read-only) | TMS events down -> confidence not established, no notice | n/a |
| `whatif` | capacity agent returns reroute options over A2A | n/a (single A2A call; client timeout) | n/a (read-only) | capacity agent down -> no options, slip handling continues | capacity agent refuses (policy) -> exception desk |
| `comms` | proactive notice draft (idempotency key notice:<shipment>:<milestone>) for confirmed slips | fallback deployment; gateway backoff with the same key | withdraw the notice draft | model down or notice guard -> template; policy or comms down -> no notice, exception desk | low-confidence or stale evidence -> exception desk review |
| `ocr` | required fields above the confidence floor and POD exception confirmed in TMS | n/a (deterministic) | n/a | instruction-like text in documents neutralised | low confidence or TMS mismatch -> claims queue |
| `claim` | claim draft within the filing window of the rule edition on the ship date (key claim:<shipment>) | gateway backoff with the same key | withdraw the claim draft | rules retrieval down -> claims queue | filing window passed or no carrier rules -> claims queue |
| `respond` | answer assembled (plus ops what-if on slips) | n/a | n/a | n/a | n/a |

## Chaos scenarios (asserted in `tests/test_chaos.py`)

| Fault | Node | Expected exit | Invariant |
|---|---|---|---|
| `model` | `track` | **degrade** | template answer from the latest TMS event, cited |
| `sor:tms` | `intake` | **degrade** | honest unavailable answer; no event IDs or locations |
| `a2a:capacity-agent` | `whatif` | **degrade** | notice still drafted; no reroute options claimed |
| `retrieval` | `claim` | **degrade** | claim queued for review; no claim draft |
| `jailbreak` | `track` | **degrade** | injected scan remark neutralised; never echoed |

## Evaluation

Golden set: `evals/golden.jsonl` · suite: `exception_agent.eval_suite:run_case` · run `python -m evals --project 18`

| Metric | Threshold | Current |
|---|---|---|
| task_success | >=0.95 | 1.00 |
| groundedness | >=0.95 | 1.00 |
| policy_violation_rate | <=0 | 0.00 |
| tool_error_rate | - | 0.04 |
| cost_per_task | <=0.002 | $0.00001 |

Cases: 21 · gate: **PASS**

## KPIs

| KPI | Target | How measured |
|---|---|---|
| Proactive notice coverage | >= 90% of confirmed slips notified before the customer asks | notice drafts vs slipped milestones with EDI/driver-app confidence |
| Interpolated locations | 0 | track answers naming a location not in TMS events (eval + reply scan) |
| False delay notices | 0 from inferred events | notices whose triggering event was inferred or stale |
| Claim filing within window | 100% of eligible claims drafted before the deadline | claim drafts vs deadline from the carrier rule edition |

## ROI sketch

"Where is my shipment?" is the top contact driver in freight customer service, and it spikes when milestones slip. Answering from TMS events with citations, and notifying customers before they ask, deflects those contacts. Refusing to guess a location when scans stop prevents promises that later break and damage trust. Building carrier claims from OCR'd documents, with the right filing window, recovers money that is otherwise lost to missed deadlines. The capacity what-if gives ops options instead of a bare alert. Costs are stream processing, TMS/claims integration, OCR and model usage.
