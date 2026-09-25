# Doctrine card: Contract review against the legal playbook (evaluator-optimizer)

<!-- GENERATED from doctrine.yaml + evals/scores.json by `python -m shared.doctrine render`. Do not edit by hand. -->

> Inbound third-party contracts are segmented and classified by clause. Each clause is reviewed against the legal playbook and checked by a deterministic evaluator; guardrails enforce the playbook floor. The contract is then routed to legal or the business owner with a risk score and approved redlines.

| Field | Value |
|---|---|
| Owner | Jagadish Meduri |
| Industry | Legal operations / procurement (any enterprise buying or selling services) |
| Maturity | **Level 3**: LLM reviewer bounded by a deterministic evaluator + guardrails, governed playbook retrieval; advisory only (lawyer approves) |
| Next rung | MCP write of the review into the CLM system (HITL) and A2A hand-off to a negotiation-drafting agent |
| Graph | `contract_review.graph:build_graph` |

## Plane dependencies

| Plane | Dependency |
|---|---|
| Experience | legal intake queue / CLM sidebar; report with findings, evidence quotes, redlines, route and disclaimer |
| Agent | LangGraph evaluator-optimizer (segment -> classify -> review <-> evaluate x3 -> guardrails -> score_and_route) |
| Knowledge | legal-playbook knowledge product via shared ContextBuilder (per-clause retrieval, ACL on senior fallbacks) |
| Data | none at runtime (contract text is the input; CLM write-back is the next rung) |

## Systems of record and semantic models

| System | Kind | Contract | Access |
|---|---|---|---|
| Legal playbook repository | document_store | `legal-playbook corpus (standard + approved redline per clause type; fallbacks senior-only)` | read |

## Knowledge: retrieval corpora and ACL

| Corpus | Owner | ACL | Temporal validity | Refresh SLA | Sensitivity |
|---|---|---|---|---|---|
| legal-playbook | Jagadish Meduri (legal operations) | legal-ops for standard positions; negotiation fallbacks legal-senior only (trimmed before ranking) | current approved edition only; playbook changes are versioned and re-evaluated in CI | on playbook approval | confidential (negotiation positions) |

## MCP / A2A contracts


Advisory agent with no writes. The rules engine (red flags, required terms, prohibited redlines) is code and acts as the control; the model only drafts within it.

## Stop conditions

- at most 3 review iterations (1 draft + 2 revisions), then guardrails enforce the floor
- prohibited redline patterns are always replaced with the approved redline
- any critical/high finding or suspected injection -> legal review

## Failure playbook (five exits per node)

| Node | Success | Retry (backoff) | Compensate | Degrade | Escalate |
|---|---|---|---|---|---|
| `segment` | numbered clauses extracted | n/a (deterministic) | n/a | instruction-like text neutralised before any model call | suspected prompt injection -> legal review route |
| `classify_clauses` | model labels each clause type | fallback deployment | n/a | keyword classifier when models are down | n/a |
| `review` | findings drafted against retrieved playbook entries | evaluator feedback loop (max 3); fallback deployment | n/a | models or playbook search down -> rules-only review (evaluator floor supplies findings + approved redlines) | n/a |
| `evaluate` | draft matches the playbook floor | sends feedback to review | n/a | n/a | unresolved feedback carried into the report |
| `guardrails` | floor enforced; no prohibited redline | n/a | prohibited or incomplete redlines replaced with approved language | n/a | n/a |
| `score_and_route` | risk score + route with disclaimer | n/a | n/a | n/a | legal_review_required for critical/high or injection |

## Chaos scenarios (asserted in `tests/test_chaos.py`)

| Fault | Node | Expected exit | Invariant |
|---|---|---|---|
| `model` | `review` | **degrade** | rules-only review still flags liability, indemnity and termination and routes to legal |
| `retrieval` | `review` | **degrade** | playbook search down -> rules-only review with the same floor and route |
| `jailbreak` | `segment` | **escalate** | injected clause neutralised, injection flagged, routed to legal |

## Evaluation

Golden set: `evals/golden.jsonl` · suite: `contract_review.eval_suite:run_case` · run `python -m evals --project 08`

| Metric | Threshold | Current |
|---|---|---|
| task_success | >=0.7 | 0.75 |
| groundedness | >=0.95 | 1.00 |
| policy_violation_rate | <=0 | 0.00 |
| tool_error_rate | - | 0.00 |
| cost_per_task | <=0.003 | $0.00033 |

Cases: 12 · gate: **PASS**

## KPIs

| KPI | Target | How measured |
|---|---|---|
| First-pass review time | -60% vs manual | contract received -> first-pass review delivered |
| Risk recall on labelled set | >= 0.9 (precision >= 0.8) | run_eval.py precision / recall |
| Unsafe redlines | 0 | guardrail blocks reaching a sent redline |

## ROI sketch

Value is lawyer hours saved on first-pass review of low-risk paper, plus faster deal cycles because low-risk paper goes straight to the business owner. Subtract token cost and the review time on escalations. Missed risks are the main cost, which is why recall is gated in CI and a lawyer approves every redline.
