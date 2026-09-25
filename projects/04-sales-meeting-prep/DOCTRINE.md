# Doctrine card: Sales meeting prep (parallel research brief)

<!-- GENERATED from doctrine.yaml + evals/scores.json by `python -m shared.doctrine render`. Do not edit by hand. -->

> Before each customer meeting, the account executive gets a one-page brief compiled in parallel from CRM history, open deals, support health and news. Every bullet cites a record, and any missing source is shown as a gap.

| Field | Value |
|---|---|
| Owner | Jagadish Meduri |
| Industry | B2B sales / revenue operations |
| Maturity | **Level 3**: read-only multi-source agent over CRM/support via MCP with citation enforcement; no writes |
| Next rung | A2A hand-off to a proposal agent + CRM write-back of the meeting plan (HITL) once AE adoption is measured |
| Graph | `meeting_prep.graph:build_graph` |

## Plane dependencies

| Plane | Dependency |
|---|---|
| Experience | calendar-triggered brief delivered to Teams/Slack 30 minutes before the meeting (markdown) |
| Agent | LangGraph map-reduce (plan -> Send fan-out research x N -> synthesize -> render_brief) with quorum rule |
| Knowledge | no corpus; findings are live system-of-record reads, cited by record id |
| Data | CRM (interactions, opportunities) and support desk via MCP; public news API direct |

## Systems of record and semantic models

| System | Kind | Contract | Access |
|---|---|---|---|
| CRM (Salesforce/Dynamics-like) | mcp | `crm.get_interaction_history, crm.get_open_deals` | read |
| Support desk | mcp | `ticketing.list_tickets` | read |
| News API | api | `public headlines by account (untrusted, cited by URL)` | read |

## Knowledge: retrieval corpora and ACL


No retrieval corpus. Every tool payload is schema-validated and sanitised before it is used, because CRM notes and ticket subjects are untrusted text.

## MCP / A2A contracts

- MCP `crm.get_interaction_history(account) -> list[Interaction]`
- MCP `crm.get_open_deals(account) -> list[Deal]`
- MCP `ticketing.list_tickets(account) -> list[Ticket]`

Read-only allowlist for identity mi-meeting-prep; the gateway does no retries because the research node owns its single transient retry.

**Tool identities (gateway allowlists):**

| Identity | Allowed tools |
|---|---|
| `mi-meeting-prep` | `crm.get_interaction_history`, `crm.get_open_deals`, `ticketing.list_tickets` |

## Stop conditions

- one research branch per source (max 4), one retry for transient errors only
- below 2 successful sources the brief is marked insufficient_data
- uncited or invented-id bullets are dropped deterministically

## Failure playbook (five exits per node)

| Node | Success | Retry (backoff) | Compensate | Degrade | Escalate |
|---|---|---|---|---|---|
| `plan` | source list chosen (requested subset or all) | n/a | n/a | n/a | n/a |
| `research` | items fetched through the gateway (schema-valid, sanitised) | one retry for timeouts / SoR unavailable | n/a (read-only) | failed source recorded as a gap; injected text neutralised | n/a (AE sees the gap and verifies manually) |
| `synthesize` | cited talking points and risks from successful findings only | fallback deployment via breaker | n/a | rule-based cited bullets when all models are down | n/a |
| `render_brief` | complete brief with deterministic tables | n/a | n/a | partial brief with gaps section | insufficient_data banner tells the AE to check the CRM directly |

## Chaos scenarios (asserted in `tests/test_chaos.py`)

| Fault | Node | Expected exit | Invariant |
|---|---|---|---|
| `model` | `synthesize` | **degrade** | brief still complete with rule-based cited bullets |
| `sor:crm` | `research` | **degrade** | CRM outage -> partial brief listing crm + deals gaps, verify manually |
| `sor` | `research` | **degrade** | all systems of record down -> insufficient_data banner, news only, nothing invented |
| `jailbreak` | `research` | **degrade** | injected CRM note neutralised; no admin text in the brief |

## Evaluation

Golden set: `evals/golden.jsonl` · suite: `meeting_prep.eval_suite:run_case` · run `python -m evals --project 04`

| Metric | Threshold | Current |
|---|---|---|
| task_success | >=0.9 | 1.00 |
| groundedness | >=0.95 | 1.00 |
| policy_violation_rate | <=0 | 0.00 |
| tool_error_rate | - | 0.38 |
| cost_per_task | <=0.002 | $0.00010 |

Cases: 12 · gate: **PASS**

## KPIs

| KPI | Target | How measured |
|---|---|---|
| AE prep time | -50% vs baseline (self-reported + calendar gap) | minutes between brief delivery and meeting start spent in CRM |
| Brief adoption | >= 70% of external meetings | briefs opened / meetings with a brief |
| Citation integrity | 100% of bullets cite an existing record | eval groundedness + zero invalid citations |

## ROI sketch

Value is AE hours returned to selling plus win-rate uplift on meetings with a brief (measured with a holdout), minus token/API cost. Stale or missing-source briefs are flagged instead of guessed, so a bad brief does not cost a deal.
