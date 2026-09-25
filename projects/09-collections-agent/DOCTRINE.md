# Doctrine card: Governed collections agent (least privilege + HITL + audit)

<!-- GENERATED from doctrine.yaml + evals/scores.json by `python -m shared.doctrine render`. Do not edit by hand. -->

> For each past-due account, a deterministic policy gate checks hardship, cease-and-desist, disputes, contact hours and frequency caps. When contact is allowed, the agent proposes a payment plan within company limits and drafts a compliant message. A human approves both before the plan is written or the message is sent, and every step is hash-chain audited.

| Field | Value |
|---|---|
| Owner | Jagadish Meduri |
| Industry | Financial services / receivables (lending, utilities, telecom) |
| Maturity | **Level 4**: write-capable agent with per-identity least privilege over MCP, deterministic compliance gates, separation of duties and tamper-evident audit |
| Next rung | A2A hand-off to a hardship-assessment agent; supervised auto-approval for low-balance plans after a measured compliance record |
| Graph | `collections_agent.graph:build_graph` |

## Plane dependencies

| Plane | Dependency |
|---|---|
| Experience | collector review console (interrupt payload with masked PII, clamped-policy notes, draft message); customer email/SMS |
| Agent | LangGraph workflow (load -> policy gate -> propose -> reviewer interrupt -> write -> send-time re-check -> finalize audit) |
| Knowledge | none at runtime (contact/plan/message policy is deterministic code - the control) |
| Data | receivables CRM (accounts, contact history, messaging) and payments ledger (plans) via MCP, per-identity gateways |

## Systems of record and semantic models

| System | Kind | Contract | Access |
|---|---|---|---|
| Receivables CRM | mcp | `crm.get_account, crm.get_contact_history (read); crm.send_customer_message (write, idempotent)` | read_write |
| Payments ledger | mcp | `payments.quote_payment_plan (read); payments.create_payment_plan (write, idempotent, approved_by)` | read_write |

## Knowledge: retrieval corpora and ACL


No retrieval. The model sees only a minimised, PII-free account view; account text returned by tools is sanitised because it is untrusted.

## MCP / A2A contracts

- MCP `crm.get_account(account_id) -> Account`
- MCP `crm.get_contact_history(account_id) -> list[Attempt]`
- MCP `crm.send_customer_message(account_id, channel, body, idempotency_key, dry_run)`
- MCP `payments.quote_payment_plan(account_id, months, discount_pct) -> Plan`
- MCP `payments.create_payment_plan(account_id, plan, approved_by, idempotency_key, dry_run)`

The scoped registry decides identity -> tool (and audits denials); each call then crosses MCP through that identity's gateway, which has its own allowlist (defence in depth).

**Tool identities (gateway allowlists):**

| Identity | Allowed tools |
|---|---|
| `mi-collections-reader` | `crm.get_account`, `crm.get_contact_history` |
| `mi-plan-proposer` | `payments.quote_payment_plan` |
| `mi-plan-writer` | `payments.create_payment_plan` |
| `mi-outreach-sender` | `crm.send_customer_message` |

## Stop conditions

- hardship / cease-and-desist / dispute -> no automated contact
- contact hours 08:00-21:00 local and 7 attempts / 7 days, re-checked at send time
- plan clamped to 12 months, 10% discount, $25 minimum installment
- nothing written or sent without a valid human reviewer (agents cannot approve)

## Failure playbook (five exits per node)

| Node | Success | Retry (backoff) | Compensate | Degrade | Escalate |
|---|---|---|---|---|---|
| `load_account` | account + history loaded via the reader identity (schema-valid, sanitised) | gateway backoff; CRM still down -> account deferred to the next batch run | n/a (read-only) | injected account text neutralised before use | n/a |
| `policy_gate` | deterministic contact decision with reasons | n/a | n/a | systems unavailable -> defer (never contact on stale data) | hardship -> hardship team |
| `hardship_referral` | referred to hardship team (audited) | n/a | n/a | n/a | hardship team owns the account |
| `no_contact` | contact suppressed with reasons (audited) | n/a | n/a | n/a | n/a |
| `defer` | next allowed contact time computed | re-run at next_allowed / next batch | n/a | n/a | n/a |
| `propose_plan` | LLM plan clamped into policy + compliant draft | fallback deployment | n/a (quote has no side effects) | models down -> policy-default plan + safe template (still reviewed); ledger quote down -> deferred to next run | n/a |
| `reviewer_approval` | valid human approves | n/a | n/a | n/a | is the human gate; invalid/agent reviewer -> auto-reject |
| `execute_plan` | plan booked once (idempotency key account:total:months) | gateway backoff on transient errors | n/a - nothing sent before the plan exists | ledger down -> write queued for replay, no outreach | n/a |
| `send_outreach` | message sent after send-time contact re-check | gateway backoff | n/a | outside hours or messaging down -> plan kept, message deferred | n/a |
| `rejected` | rejection recorded | n/a | n/a | n/a | n/a |
| `finalize` | audit hash chain verified | n/a | n/a | n/a | broken chain -> security/compliance review |

## Chaos scenarios (asserted in `tests/test_chaos.py`)

| Fault | Node | Expected exit | Invariant |
|---|---|---|---|
| `model` | `propose_plan` | **degrade** | policy-default plan + compliant template; still human-approved before sending |
| `sor` | `load_account` | **retry** | CRM down -> deferred to next run; nothing written or sent |
| `sor:payments.create_payment_plan` | `execute_plan` | **degrade** | ledger down after approval -> plan write queued, no message sent |
| `jailbreak` | `load_account` | **degrade** | injected account text neutralised; plan within policy; no injected text in outbound message |

## Evaluation

Golden set: `evals/golden.jsonl` · suite: `collections_agent.eval_suite:run_case` · run `python -m evals --project 09`

| Metric | Threshold | Current |
|---|---|---|
| task_success | >=0.9 | 1.00 |
| groundedness | - | n/a |
| policy_violation_rate | <=0 | 0.00 |
| tool_error_rate | - | 0.05 |
| cost_per_task | <=0.002 | $0.00004 |

Cases: 13 · gate: **PASS**

## KPIs

| KPI | Target | How measured |
|---|---|---|
| Promise-to-pay / plan acceptance | +15% vs manual outreach (holdout) | plans accepted / contacts attempted |
| Compliance incidents | 0 (contact-rule, disclosure, threat-language) | audit review + outbox scan |
| Collector handle time | -50% per account | review time per approved plan |

## ROI sketch

Value is recovered balances from more timely, affordable plans, plus collector hours saved on drafting. Subtract token cost and reviewer time. Avoided regulatory penalties and complaints are the main risk-side value; they are not modelled as a number, but every guardrail is audited so they can be.
