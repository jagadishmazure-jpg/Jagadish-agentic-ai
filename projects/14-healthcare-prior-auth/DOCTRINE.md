# Doctrine card: Healthcare prior authorization - draft-only packets with clinician sign-off

<!-- GENERATED from doctrine.yaml + evals/scores.json by `python -m shared.doctrine render`. Do not edit by hand. -->

> A provider office asks for prior authorization. The clinical note is PHI-redacted before any model or context pack sees it, and a log filter redacts PHI in every log record. Member eligibility comes from the payer API over MCP; a failure means "unknown", never "eligible". Medical policies are retrieved with plan ACL (Gold never sees Silver rules) and plan-year validity as of the date of service. Criteria are checked deterministically. A coverage-language subgraph, behind a runtime kill switch, words the summary with checked citations. The agent can only save a draft; a registered clinician signs before submission. Members get status only, and a hard guardrail blocks medical advice.

| Field | Value |
|---|---|
| Owner | Jagadish Meduri |
| Industry | Healthcare (payer / provider utilization management) |
| Maturity | **Level 3**: assistive with hard boundaries - research, criteria and packet drafting are automated; submission needs a clinician signature, the member channel is status-only, and coverage wording has a kill switch |
| Next rung | FHIR/Da Vinci PAS integration (CRD/DTR) for real payer rules and electronic submission, keeping clinician sign-off and the member-channel guardrail |
| Graph | `prior_auth.graph:build_graph` |

## Plane dependencies

| Plane | Dependency |
|---|---|
| Experience | provider portal (request + clinician sign-off console) and member app/chat (status only, medical-advice guardrail) |
| Agent | LangGraph PA graph (intake -> [eligibility || policy] -> criteria -> coverage_language subgraph -> draft_packet -> clinician_approval -> submit | member_reply), checkpoints + interrupt(), kill switch on the coverage-language subgraph |
| Knowledge | medical-policies corpus on the shared ContextBuilder - plan ACL groups, plan-year validity as-of date of service, UM guidance ACL'd to medical directors; clinical note PHI-redacted before packing |
| Data | payer eligibility API and PA portal via MCP servers; three identities (reader, drafter, submitter); portal enforces clinician signature server-side |

## Systems of record and semantic models

| System | Kind | Contract | Access |
|---|---|---|---|
| Eligibility API | api | `eligibility.check_eligibility(member_id, dos) -> eligible, plan, plan_year (MCP-wrapped 270/271)` | read |
| PA portal | mcp | `pa_portal.save_draft (write), pa_portal.submit (write; clinician signature required), pa_portal.get_status (read)` | read_write |

## Knowledge: retrieval corpora and ACL

| Corpus | Owner | ACL | Temporal validity | Refresh SLA | Sensitivity |
|---|---|---|---|---|---|
| medical-policies | Jagadish Meduri (medical policy) | common policies all plans; plan-specific policies plan:<id> only; UM-MD-GUIDE-INT um-medical-director only | plan-year editions (2025, 2026) with valid_from/valid_to; retrieved as-of the date of service | plan-year publish plus mid-year bulletins within 24 hours | internal |

Clinical notes are per-request evidence: PHI-redacted (names, MRN, DOB, SSN, phone, email) before packing and never indexed.

## MCP / A2A contracts

- MCP `eligibility.check_eligibility(member_id, dos)`
- MCP `pa_portal.save_draft(packet, idempotency_key, dry_run)`
- MCP `pa_portal.submit(draft_id, signed_by, idempotency_key, dry_run)`
- MCP `pa_portal.get_status(member_id)`

Peer-to-peer review scheduling with the payer's UM agent would be the first A2A peer.

**Tool identities (gateway allowlists):**

| Identity | Allowed tools |
|---|---|
| `mi-pa-reader` | `eligibility.check_eligibility`, `pa_portal.get_status` |
| `mi-pa-drafter` | `pa_portal.save_draft` |
| `mi-pa-submitter` | `pa_portal.submit` |

## Stop conditions

- the agent only drafts; submission requires a registered clinician's sign-off, enforced in the graph and again by the portal
- eligibility failure -> "unknown" flagged on the packet; ineligible on the date of service -> no packet
- member channel is status-only; medical-advice questions are refused with the nurse line; advice in any model output is blocked
- coverage-language kill switch off -> packet has the criteria checklist and citations but no generated wording
- PHI never reaches logs or model context (redaction + log filter)

## Failure playbook (five exits per node)

| Node | Success | Retry (backoff) | Compensate | Degrade | Escalate |
|---|---|---|---|---|---|
| `intake` | note redacted, facts extracted deterministically, channel routed | n/a | n/a | n/a | instruction-like text in the note -> removed and flagged for the clinician |
| `eligibility` | eligible / ineligible on DOS with matching plan | gateway backoff | n/a (read-only) | API down or error -> status unknown, packet flagged "verify before service" | plan on card differs from payer plan -> unknown + escalation record |
| `policy` | plan- and plan-year-scoped policies retrieved with citations | n/a (idempotent search) | n/a | retrieval down -> no policies, criteria unknown | n/a |
| `criteria` | deterministic met/unmet list from retrieved policies | n/a | n/a | required policy not retrieved -> criteria unknown | member ineligible on DOS -> no packet, provider told to verify coverage |
| `coverage_language` | model wording that cites only retrieved policies and contains no PHI | fallback deployment | n/a | kill switch -> no wording; model down or bad citation/PHI -> template | n/a |
| `draft_packet` | draft saved in the PA portal (idempotent per thread) | gateway backoff | draft deletable by staff; nothing submitted | portal down -> packet kept in state, nothing saved or submitted | n/a |
| `clinician_approval` | registered clinician approves or rejects | n/a | n/a | n/a | non-clinician sign-off refused |
| `submit` | portal accepts the clinician-signed submission | gateway backoff; idempotency key submit:<draft> | withdraw request via portal (staff) | portal down -> signed draft stays, retried later | n/a |
| `member_reply` | status of the member's requests, no clinical content | fallback deployment | n/a | model down -> template; advice in output -> blocked + nurse line | medical-advice question -> refusal + nurse line |

## Chaos scenarios (asserted in `tests/test_chaos.py`)

| Fault | Node | Expected exit | Invariant |
|---|---|---|---|
| `model` | `coverage_language` | **degrade** | template criteria wording; packet still clinician-signed and submitted |
| `retrieval` | `policy` | **degrade** | criteria unknown, no citations claimed |
| `sor:eligibility` | `eligibility` | **degrade** | eligibility unknown flagged on the packet, never assumed eligible |
| `sor:pa_portal` | `draft_packet` | **degrade** | nothing saved, nothing submitted |
| `jailbreak` | `intake` | **escalate** | injected note text removed from the packet and flagged for the clinician |

## Evaluation

Golden set: `evals/golden.jsonl` · suite: `prior_auth.eval_suite:run_case` · run `python -m evals --project 14`

| Metric | Threshold | Current |
|---|---|---|
| task_success | >=0.95 | 1.00 |
| groundedness | >=0.95 | 1.00 |
| policy_violation_rate | <=0 | 0.00 |
| tool_error_rate | - | 0.04 |
| cost_per_task | <=0.002 | $0.00003 |

Cases: 20 · gate: **PASS**

## KPIs

| KPI | Target | How measured |
|---|---|---|
| Packet preparation time | < 10 minutes from request to clinician-ready draft | request -> interrupt timestamps |
| First-pass approval rate | up vs baseline (fewer pends for missing documentation) | payer determinations on submitted packets |
| PHI in logs or model context | 0 occurrences | log scan + context pack scan for names, MRN, DOB, SSN, phone |
| Medical advice in member channel | 0 messages | guardrail hits + sampled QA of member replies |

## ROI sketch

Prior authorization is a large administrative load on provider staff and a common cause of care delays and pended requests for missing documentation. Assembling a criteria-checked, cited packet cuts staff preparation time and raises first-pass approvals because gaps show up before submission. The clinician still signs every request and members never get clinical advice from the bot, so the gain comes without shifting clinical risk. Costs are model usage, payer API access and medical-policy content upkeep.
