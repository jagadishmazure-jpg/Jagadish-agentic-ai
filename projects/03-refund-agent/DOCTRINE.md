# Doctrine card: Refund agent (customer care)

<!-- GENERATED from doctrine.yaml + evals/scores.json by `python -m shared.doctrine render`. Do not edit by hand. -->

> Policy-true refunds in seconds: deterministic eligibility over OMS data, policy text retrieved as-of the delivery date, money moves only through an idempotent payment tool, and anything >= $50, suspicious or evidence-poor pauses for a human.

| Field | Value |
|---|---|
| Owner | Jagadish Meduri |
| Industry | Retail & e-commerce |
| Maturity | **Level 5**: governed autonomy - small refunds are paid without a human, under policy, with traces and a HITL node on the high side of risk |
| Next rung | raise the auto-approve limit only after leakage and second-contact metrics stay green for a quarter |
| Graph | `refund_agent.graph:build_graph` |

## Plane dependencies

| Plane | Dependency |
|---|---|
| Experience | web / app chat and email; channel passes customer id + email; replies are short, template-guarded, never expose policy IDs or fraud logic |
| Agent | LangGraph StateGraph (classify -> verify -> order -> policy -> decide -> HITL -> refund -> reply) with MemorySaver checkpoints and interrupt() |
| Knowledge | refund-policy corpus via shared ContextBuilder - chunk per rule, temporal validity (as-of delivery date), ACL (fraud rule internal-only), sanitizer |
| Data | OMS orders (gold order header), CRM customer + case timeline, payment provider ledger - all via MCP through the tool gateway |

## Systems of record and semantic models

| System | Kind | Contract | Access |
|---|---|---|---|
| OMS | mcp | `oms.get_order / oms.mark_order_refunded` | read_write |
| CRM | mcp | `crm.verify_customer / crm.add_case_note` | read_write |
| Payment provider | mcp | `payments.issue_refund (provider-side idempotency)` | write |

## Knowledge: retrieval corpora and ACL

| Corpus | Owner | ACL | Temporal validity | Refresh SLA | Sensitivity |
|---|---|---|---|---|---|
| refund-policy | Jagadish Meduri (customer-care policy product) | RP-1..RP-6 everyone; RP-7 fraud rule only groups fraud-ops, refund-agent | valid_from / valid_to per edition; retrieved as-of the order delivery date (2025 edition superseded) | event-driven on policy publish; nightly hygiene | internal |

## MCP / A2A contracts

- MCP `oms.get_order`
- MCP `oms.mark_order_refunded`
- MCP `crm.verify_customer`
- MCP `crm.add_case_note`
- MCP `payments.issue_refund`

Single journey agent; a fraud domain agent would be the first A2A peer (today fraud review is a queue handoff).

**Tool identities (gateway allowlists):**

| Identity | Allowed tools |
|---|---|
| `mi-refund-agent` | `oms.get_order`, `oms.mark_order_refunded`, `crm.verify_customer`, `crm.add_case_note`, `payments.issue_refund` |

## Stop conditions

- deterministic graph - no open-ended loops; every path ends in compose_reply
- payments.issue_refund quota 3 per run (gateway) and one refund per order (RP-3 + idempotency key refund:<order>)
- refunds >= $50, injected instructions or missing policy evidence stop at a human approval interrupt
- fraud indicators stop before any money-moving tool is reachable

## Failure playbook (five exits per node)

| Node | Success | Retry (backoff) | Compensate | Degrade | Escalate |
|---|---|---|---|---|---|
| `classify_intent` | intent label from the model | fallback deployment via model circuit breaker | n/a (read-only) | keyword classifier when every model deployment is down | n/a - downstream nodes are deterministic |
| `verify_identity` | CRM verifies email and OMS confirms order ownership | gateway timeout + breaker per SOR | n/a (read-only) | n/a - never guess identity | OMS/CRM unavailable -> escalate to a human with an honest reason |
| `check_order` | order loaded from OMS (schema-validated) | gateway breaker | n/a (read-only) | n/a - never invent order state | OMS unavailable -> escalate |
| `check_refund_policy` | deterministic rules + policy text retrieved as-of delivery date with citations | n/a (local rules); retrieval errors are typed | n/a | retrieval down or rule missing -> known-policy cache citations and auto-refund disabled (routed to human approval) | prompt injection in customer text -> human approval regardless of amount |
| `human_approval` | reviewer approves / rejects via Command(resume) | durable - interrupt state survives restarts in the checkpointer | n/a | n/a | SLA timeout -> deny or queue, never silent pay (operational policy) |
| `issue_refund` | provider refund + OMS flag + CRM note | payments retried 3x with backoff; first CRM failure after money moved crashes to the checkpoint and the replay is deduped by the provider key | n/a - payment is idempotent, follow-up writes are queued not reversed | provider down -> refund queued (reply says not yet sent); OMS/CRM follow-ups queued to outbox | quota exceeded or repeated provider failure -> queued refund reviewed by payments ops |
| `notify_rejection` | CRM note written | n/a | n/a | CRM down -> note queued to outbox | n/a |
| `deny` | denial recorded with policy citation | n/a | n/a | n/a | customer can reply to reach an agent (reply copy) |
| `fraud_review` | case handed to fraud queue, CRM note | n/a | n/a | CRM down -> note queued | always escalates to the fraud team (by design) |
| `escalate` | handoff recorded | n/a | n/a | n/a | human agent queue |
| `compose_reply` | model-written reply passing the output guard | fallback deployment | n/a | vetted template when the model is down or the reply leaks internals | n/a |

## Chaos scenarios (asserted in `tests/test_chaos.py`)

| Fault | Node | Expected exit | Invariant |
|---|---|---|---|
| `model` | `classify_intent` | **degrade** | same outcome via keyword classifier + template reply; exactly one refund |
| `retrieval` | `check_refund_policy` | **degrade** | no auto refund; paused for human approval with cached policy citations |
| `sor:oms` | `verify_identity` | **escalate** | escalated; no money moved; nothing invented |
| `sor:payments` | `issue_refund` | **degrade** | refund queued with idempotency key; reply says not yet sent |
| `sor:crm.add_case_note` | `issue_refund` | **degrade** | worker replay deduped; money moved exactly once; CRM note queued |
| `sor:crm.add_case_note*1` | `issue_refund` | **retry** | transient CRM failure recovered by checkpoint replay; one refund |
| `jailbreak` | `check_refund_policy` | **escalate** | injected instructions never auto-pay; human approval required |

## Evaluation

Golden set: `evals/golden.jsonl` · suite: `refund_agent.eval_suite:run_case` · run `python -m evals --project 03`

| Metric | Threshold | Current |
|---|---|---|
| task_success | >=0.95 | 1.00 |
| groundedness | >=0.95 | 1.00 |
| policy_violation_rate | <=0 | 0.00 |
| tool_error_rate | <=0.05 | 0.00 |
| cost_per_task | <=0.002 | $0.00004 |

Cases: 12 · gate: **PASS**

## KPIs

| KPI | Target | How measured |
|---|---|---|
| Refund containment | >= 60% of refund intents closed without an agent | closed threads with no human touch and no second contact within 7 days |
| Refund leakage | 0 refunds outside policy | weekly audit sample of issued refunds vs policy rules |
| Time to honest status | < 10 s p95 | agent.run span duration to first reply |
| HITL aging | p95 approval < 4 business hours | interrupt -> resume timestamps |

## ROI sketch

Value comes from contained refund contacts (fully loaded agent cost avoided), minus goodwill leakage that the policy nodes prevent, minus HITL reviewer time for refunds of $50 or more. Tokens are a small line item next to integration with OMS, CRM and payments. Second contacts caused by wrong answers are subtracted, which is why replies are template-guarded and never claim money moved before the provider confirms it.
