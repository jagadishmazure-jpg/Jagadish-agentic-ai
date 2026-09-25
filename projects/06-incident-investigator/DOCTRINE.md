# Doctrine card: SRE incident investigator (ReAct + HITL rollback)

<!-- GENERATED from doctrine.yaml + evals/scores.json by `python -m shared.doctrine render`. Do not edit by hand. -->

> On an alert, an autonomous investigator reads metrics, deploys, logs and runbooks. It writes an evidence-cited root-cause report. It can propose a rollback, but a rollback runs only after a human approves it.

| Field | Value |
|---|---|
| Owner | Jagadish Meduri |
| Industry | Technology operations / SRE (any digital business) |
| Maturity | **Level 4**: agentic tool loop over MCP ops tools with hard stop conditions, evidence validation and a HITL-gated idempotent write |
| Next rung | A2A hand-off to a change-management agent (CAB ticket) and auto-approval of low-risk rollbacks after a measured precision bar |
| Graph | `incident_agent.graph:build_graph` |

## Plane dependencies

| Plane | Dependency |
|---|---|
| Experience | PagerDuty/Teams alert card; approver resumes the paused thread with approve/reject; report posted to the incident channel |
| Agent | create_agent ReAct investigator (guardrail middleware - steps, tool budget, loop detection, model-outage stop) inside an outer LangGraph with report validation |
| Knowledge | sre-runbooks knowledge product via shared ContextBuilder (hybrid retrieval, ACL - DBA-only runbooks trimmed, as-of editions) |
| Data | observability + deploy system via the ops MCP server (logs, metrics, deploys, rollback) |

## Systems of record and semantic models

| System | Kind | Contract | Access |
|---|---|---|---|
| Observability stack (logs / metrics) | mcp | `ops.query_logs, ops.get_metrics` | read |
| Deploy system (CD) | mcp | `ops.recent_deploys (read), ops.rollback_deploy (write, idempotent, HITL)` | read_write |
| SRE runbooks repo | document_store | `sre-runbooks corpus (versioned, ACL by team)` | read |

## Knowledge: retrieval corpora and ACL

| Corpus | Owner | ACL | Temporal validity | Refresh SLA | Sensitivity |
|---|---|---|---|---|---|
| sre-runbooks | Jagadish Meduri (SRE platform) | sre group; database failover runbooks dba-only (trimmed before ranking) | editions with valid_from / valid_to; lookups as-of the incident date | on merge to the runbooks repo | internal |

## MCP / A2A contracts

- MCP `ops.query_logs(service, pattern, minutes) -> {lines}`
- MCP `ops.get_metrics(service, metric, minutes) -> {baseline, current, unit, change_at}`
- MCP `ops.recent_deploys(service, hours) -> {deploys}`
- MCP `ops.rollback_deploy(service, to_version, idempotency_key=rollback:<svc>:<ver>, dry_run) -> {from, to}`

Identity mi-incident-investigator. The rollback interrupt stays in the graph; the MCP write runs only after the resumed approval and has a quota of 3 per graph.

**Tool identities (gateway allowlists):**

| Identity | Allowed tools |
|---|---|
| `mi-incident-investigator` | `ops.query_logs`, `ops.get_metrics`, `ops.recent_deploys`, `ops.rollback_deploy` |

## Stop conditions

- max 8 model turns, max 20 tool-cost units per investigation
- identical tool call twice -> not executed; two loop hits -> stop
- all model deployments down -> stop and escalate with evidence gathered so far
- rollback only via interrupt + human approval; report needs >= 2 observed evidence ids

## Failure playbook (five exits per node)

| Node | Success | Retry (backoff) | Compensate | Degrade | Escalate |
|---|---|---|---|---|---|
| `open_case` | alert converted into the investigation prompt | n/a | n/a | n/a | n/a |
| `investigator` | tools observed with evidence ids; rollback proposed only when the runbook allows it | fallback model deployment; gateway backoff on transient tool errors | rollback is itself the compensation for a bad deploy (approved, idempotent) | failed tool / runbook search -> gap noted in the observation, no write actions; injected log text neutralised | guardrail stop (steps, budget, loop, model outage) -> incomplete report to on-call |
| `write_report` | schema-valid report citing >= 2 observed evidence ids | n/a - no argue-with-the-model loops | n/a | n/a | fabricated evidence / degraded tools / unparseable -> needs_human |

## Chaos scenarios (asserted in `tests/test_chaos.py`)

| Fault | Node | Expected exit | Invariant |
|---|---|---|---|
| `model` | `investigator` | **escalate** | incomplete report escalated; no rollback |
| `retrieval` | `investigator` | **degrade** | runbook search down -> no rollback proposed; needs_human |
| `sor` | `investigator` | **degrade** | telemetry down -> undetermined root cause, needs_human; no rollback |
| `sor:ops.rollback_deploy` | `investigator` | **degrade** | approved rollback that fails to execute is reported NOT EXECUTED and handed to on-call |
| `jailbreak` | `investigator` | **degrade** | injected log line neutralised; upstream incident still diagnosed without a rollback |

## Evaluation

Golden set: `evals/golden.jsonl` · suite: `incident_agent.eval_suite:run_case` · run `python -m evals --project 06`

| Metric | Threshold | Current |
|---|---|---|
| task_success | >=0.9 | 1.00 |
| groundedness | >=0.9 | 1.00 |
| policy_violation_rate | <=0 | 0.00 |
| tool_error_rate | - | 0.10 |
| cost_per_task | <=0.005 | $0.00019 |

Cases: 13 · gate: **PASS**

## KPIs

| KPI | Target | How measured |
|---|---|---|
| MTTR | -30% on deploy-correlated incidents | alert -> mitigated, incidents with vs without the agent |
| Root-cause precision | >= 85% confirmed by the incident review | post-incident review agrees with report root cause |
| Unapproved writes | 0 | rollback_deploy calls without an approval record |

## ROI sketch

Value is on-call engineer minutes saved per incident, plus revenue protected by a faster MTTR on customer-facing services. Subtract token and tool cost (capped per investigation) and the approver's time. Wrong diagnoses are caught by the evidence gate and the review before they cost anything.
