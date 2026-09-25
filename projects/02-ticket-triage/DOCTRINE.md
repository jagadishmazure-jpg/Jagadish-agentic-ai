# Doctrine card: Support ticket triage router

<!-- GENERATED from doctrine.yaml + evals/scores.json by `python -m shared.doctrine render`. Do not edit by hand. -->

> Every inbound ticket is PII-redacted, classified into a strict schema and routed to the right queue with an SLA - or to a human when the model is unsure, unavailable, or being manipulated.

| Field | Value |
|---|---|
| Owner | Jagadish Meduri |
| Industry | Cross-industry (customer support / service desk) |
| Maturity | **Level 3**: LLM classification with schema validation, bounded repair and confidence gates; one idempotent write (ticket create) |
| Next rung | attach knowledge-base answer suggestions (context builder) to routed tickets and measure agent handle time |
| Graph | `ticket_triage.graph:build_graph` |

## Plane dependencies

| Plane | Dependency |
|---|---|
| Experience | email / web form / chat intake; customer receives a queue-specific acknowledgement or clarifying question |
| Agent | LangGraph router (redact -> classify -> validate -> bounded repair -> confidence gate -> queue handler) |
| Knowledge | none at runtime (classification rubric lives in the prompt; KB answer suggestions are the next rung) |
| Data | service desk (ServiceNow/Zendesk-like) as system of record for created tickets, via MCP |

## Systems of record and semantic models

| System | Kind | Contract | Access |
|---|---|---|---|
| Service desk | mcp | `ticketing.create_ticket (write, idempotency_key, dry_run default)` | write |

## Knowledge: retrieval corpora and ACL


No retrieval; inputs are the ticket itself, treated as untrusted data (PII-redacted and injection-sanitised before the model sees it).

## MCP / A2A contracts

- MCP `ticketing.create_ticket(queue, subject, summary, priority, idempotency_key, dry_run) -> CreatedTicket`

Gateway identity mi-ticket-triage, allowlist = ticketing.create_ticket only; only redacted text crosses the boundary.

**Tool identities (gateway allowlists):**

| Identity | Allowed tools |
|---|---|
| `mi-ticket-triage` | `ticketing.create_ticket` |

## Stop conditions

- at most 1 schema repair, then human review
- confidence < 0.40 or intent 'other' -> human; < 0.60 -> one clarifying question
- suspected prompt injection -> human review (never auto-routed)
- one ticket per inbound id (idempotency key triage:<id>)

## Failure playbook (five exits per node)

| Node | Success | Retry (backoff) | Compensate | Degrade | Escalate |
|---|---|---|---|---|---|
| `redact_pii` | PII replaced with placeholders; vault never leaves the node | n/a (deterministic) | n/a | injected instructions neutralised in the text sent to the model | suspected prompt injection -> human review |
| `classify` | model returns classification JSON | fallback deployment via breaker | n/a | all deployments down -> human queue (never a guessed route) | n/a |
| `validate` | output parses into TicketClassification | one repair attempt | n/a | n/a | invalid after repair / low confidence / 'other' -> human review |
| `repair` | corrected JSON returned | fallback deployment | n/a | model down -> human queue | n/a |
| `clarify` | one clarifying question to the customer | fallback deployment | n/a | templated clarifying question when models are down | n/a |
| `human_review` | ticket created in triage_human_queue with the reason | gateway backoff | n/a | ticketing outage -> outbox | is the escalation target (triage desk) |
| `billing_queue` | billing ticket created in the service desk (idempotent on inbound id) + SLA ack | gateway backoff on transient ticketing errors | n/a (create is idempotent; replay returns the same ticket) | ticketing outage -> ticket queued in the outbox for replay; customer still gets the ack | critical urgency pages on-call |
| `tech_support_queue` | technical ticket created in the service desk (idempotent on inbound id) + SLA ack | gateway backoff on transient ticketing errors | n/a (create is idempotent; replay returns the same ticket) | ticketing outage -> ticket queued in the outbox for replay; customer still gets the ack | critical urgency pages on-call |
| `account_security_queue` | account access ticket created in the service desk (idempotent on inbound id) + SLA ack | gateway backoff on transient ticketing errors | n/a (create is idempotent; replay returns the same ticket) | ticketing outage -> ticket queued in the outbox for replay; customer still gets the ack | critical urgency pages on-call |
| `product_feedback_queue` | feature request ticket created in the service desk (idempotent on inbound id) + SLA ack | gateway backoff on transient ticketing errors | n/a (create is idempotent; replay returns the same ticket) | ticketing outage -> ticket queued in the outbox for replay; customer still gets the ack | critical urgency pages on-call |
| `retention_queue` | cancellation ticket created in the service desk (idempotent on inbound id) + SLA ack | gateway backoff on transient ticketing errors | n/a (create is idempotent; replay returns the same ticket) | ticketing outage -> ticket queued in the outbox for replay; customer still gets the ack | critical urgency pages on-call |

## Chaos scenarios (asserted in `tests/test_chaos.py`)

| Fault | Node | Expected exit | Invariant |
|---|---|---|---|
| `model` | `classify` | **degrade** | routed to the human queue with 'classifier unavailable', no guessed route |
| `sor` | `billing_queue` | **degrade** | route kept, ticket queued in outbox with idempotency key triage:<id> |
| `jailbreak` | `redact_pii` | **escalate** | injected ticket goes to human review, not the requested queue |

## Evaluation

Golden set: `evals/golden.jsonl` · suite: `ticket_triage.eval_suite:run_case` · run `python -m evals --project 02`

| Metric | Threshold | Current |
|---|---|---|
| task_success | >=0.9 | 1.00 |
| groundedness | - | n/a |
| policy_violation_rate | <=0 | 0.00 |
| tool_error_rate | <=0.05 | 0.00 |
| cost_per_task | <=0.002 | $0.00006 |

Cases: 12 · gate: **PASS**

## KPIs

| KPI | Target | How measured |
|---|---|---|
| Auto-route accuracy | >= 90% on golden + weekly sample | queue chosen == queue after human re-route |
| Time to first queue | < 1 min p95 | ticket received -> service-desk ticket created |
| PII leakage to model or ticket store | 0 | eval + DLP scan of prompts and created tickets |

## ROI sketch

Value is triage-desk minutes saved per ticket plus SLA breaches avoided through correct urgency paging, minus token cost and the human-review load created by low-confidence and injection escalations (tracked, not hidden). Mis-routes are counted against value via re-route rate.
