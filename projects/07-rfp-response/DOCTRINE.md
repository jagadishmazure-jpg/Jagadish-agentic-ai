# Doctrine card: RFP / security-questionnaire response agent

<!-- GENERATED from doctrine.yaml + evals/scores.json by `python -m shared.doctrine render`. Do not edit by hand. -->

> Incoming RFPs are split into sections and each question is drafted from the approved answer library only. A critic checks citations and coverage, and a compliance gate strips banned claims and flags export-control terms. Anything the library cannot support goes to an SME.

| Field | Value |
|---|---|
| Owner | Jagadish Meduri |
| Industry | B2B SaaS sales / presales and security-assurance teams |
| Maturity | **Level 3**: governed knowledge product + planner/worker/critic with deterministic compliance gate; read-only, human submits |
| Next rung | MCP write to the RFP portal / CRM opportunity (HITL) and A2A request to the legal-review agent for export-control hits |
| Graph | `rfp_agent.graph:build_graph` |

## Plane dependencies

| Plane | Dependency |
|---|---|
| Experience | presales workspace / Teams; draft markdown with per-answer sources, SME and legal flags |
| Agent | LangGraph planner -> Send per section -> worker subgraph (retrieve -> draft -> critic loop) -> compliance gate -> assemble |
| Knowledge | rfp-answer-library knowledge product via shared ContextBuilder (hybrid retrieval, ACL, as-of editions, sanitiser) |
| Data | none at runtime (the library is the system of record for approved answers; CRM/portal write-back is the next rung) |

## Systems of record and semantic models

| System | Kind | Contract | Access |
|---|---|---|---|
| Approved answer library (content system) | document_store | `rfp-answer-library corpus (entries with owner, ACL, validity)` | read |

## Knowledge: retrieval corpora and ACL

| Corpus | Owner | ACL | Temporal validity | Refresh SLA | Sensitivity |
|---|---|---|---|---|---|
| rfp-answer-library | Jagadish Meduri (presales + security assurance) | presales + deal-desk; pricing entries deal-desk only (trimmed before ranking) | editions with valid_from / valid_to; as_of = RFP submission date | weekly + on answer approval | internal; pricing confidential |

## MCP / A2A contracts


Read-only drafting agent; the library is served in-process by the shared ContextBuilder. A human reviews and submits the final document.

## Stop conditions

- critic sends a draft back at most twice, then SME
- no library hit -> SME immediately (no model-memory answers)
- banned claims removed; export-control terms force legal review

## Failure playbook (five exits per node)

| Node | Success | Retry (backoff) | Compensate | Degrade | Escalate |
|---|---|---|---|---|---|
| `plan` | model splits the RFP into sections/questions (schema-valid) | fallback deployment | n/a | deterministic header/Qn parser (bad output or all models down) | n/a |
| `section_worker` | each question drafted from retrieved library entries and passes the critic | critic loop (max 2 revisions); fallback model deployment | n/a | library outage -> SME for every question; models down -> verbatim cited library sentences; injected text neutralised | no library hit / budget spent -> needs_sme |
| `compliance` | no banned claims or export-control terms | n/a (deterministic) | banned sentences removed; answer with nothing citable left -> SME | n/a | export-control terms flagged for legal |
| `assemble` | ready document with sources appendix | n/a | n/a | n/a | needs_sme / legal_review_required status for the human owner |

## Chaos scenarios (asserted in `tests/test_chaos.py`)

| Fault | Node | Expected exit | Invariant |
|---|---|---|---|
| `model` | `plan` | **degrade** | deterministic plan + verbatim cited drafts; same 8 answered, Q8 to SME |
| `retrieval` | `section_worker` | **degrade** | library down -> every question to SME, nothing drafted from model memory |
| `jailbreak` | `section_worker` | **degrade** | poisoned library entry neutralised; no admin text in the document |

## Evaluation

Golden set: `evals/golden.jsonl` · suite: `rfp_agent.eval_suite:run_case` · run `python -m evals --project 07`

| Metric | Threshold | Current |
|---|---|---|
| task_success | >=0.9 | 1.00 |
| groundedness | >=0.95 | 1.00 |
| policy_violation_rate | <=0 | 0.00 |
| tool_error_rate | - | 0.00 |
| cost_per_task | <=0.003 | $0.00011 |

Cases: 12 · gate: **PASS**

## KPIs

| KPI | Target | How measured |
|---|---|---|
| First-draft coverage | >= 70% of questions answered from the library | accepted answers / questions |
| Response cycle time | -50% vs baseline | RFP received -> submitted |
| Compliance escapes | 0 banned claims or unreviewed export-control terms submitted | eval + submission audit |

## ROI sketch

Value is presales and SME hours saved per RFP, plus more RFPs bid at the same headcount, plus lower legal risk from banned claims that are blocked before submission. Subtract token cost and library curation. SME escalations are counted as remaining work, not hidden.
