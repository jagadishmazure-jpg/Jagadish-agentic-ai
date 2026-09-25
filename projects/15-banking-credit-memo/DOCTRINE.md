# Doctrine card: Banking credit memo - semantic-layer financials, ownership graph, dual control

<!-- GENERATED from doctrine.yaml + evals/scores.json by `python -m shared.doctrine render`. Do not edit by hand. -->

> Prepares a commercial credit memo and books the limit only under dual control. A planner model proposes analyses, but KYC is a mandatory graph edge that neither the primary nor the fallback model can route around. KYC walks a beneficial-ownership graph as of the application date (edges carry validity) and screens every person. Financials come only from a governed semantic layer, get_measure(name, grain, filters), dry-run first and never raw SQL. The existing PD/rating model is a tool. Credit policy limits are retrieved as of the application date. The model drafts the memo; a critic checks every figure and citation. Two distinct approvers (the second a credit officer) are required, and the loan system checks that again.

| Field | Value |
|---|---|
| Owner | Jagadish Meduri |
| Industry | Banking (commercial lending) |
| Maturity | **Level 3**: analyst assist with hard controls - memo preparation is automated, credit decisions and bookings stay with two humans, and KYC is structurally mandatory |
| Next rung | connect to the bank's metric store (dbt/semantic layer on the lakehouse) and entity-resolution service for ownership, and add annual-review memos for the existing book under the same controls |
| Graph | `credit_memo.graph:build_graph` |

## Plane dependencies

| Plane | Dependency |
|---|---|
| Experience | RM workbench (request, memo review) and credit officer approval queue (first/second approval interrupts) |
| Agent | LangGraph credit-memo graph (planner -> kyc -> [financials || risk || policy] -> memo -> first_approval -> second_approval -> book_limit) with checkpoints; KYC is an unconditional edge |
| Knowledge | beneficial-ownership graph with valid_from/valid_to (graph RAG, citable OWN edge ids) + credit-policy corpus (editions as-of the application date, ACL) on the shared ContextBuilder |
| Data | governed semantic layer (gold credit mart), KYC screening, PD/rating model endpoint and loan system via MCP; reader and booker identities |

## Systems of record and semantic models

| System | Kind | Contract | Access |
|---|---|---|---|
| Semantic layer (gold credit mart) | semantic_model | `semantic.get_measure(name, grain, filters, dry_run) - registered measures only, borrower_id mandatory, no SQL` | read |
| KYC screening | api | `kyc.screen(names) -> hits, list_version` | read |
| PD / rating model | api | `risk_model.score(borrower_id) -> pd, grade, model_version` | read |
| Loan system | mcp | `loan_system.set_credit_limit(borrower_id, amount, approvals, idempotency_key, dry_run) - dual control enforced server-side` | write |

## Knowledge: retrieval corpora and ACL

| Corpus | Owner | ACL | Temporal validity | Refresh SLA | Sensitivity |
|---|---|---|---|---|---|
| credit-policy | Jagadish Meduri (credit policy) | credit-risk group; special-assets watchlist special-assets only | 2025 and 2026 editions of leverage/DSCR limits; retrieved as-of the application date | on credit committee approval | internal |
| beneficial-ownership-graph | Jagadish Meduri (KYC data) | credit-risk and KYC roles only | every ownership edge has valid_from/valid_to; walked as-of the application date | on corporate registry change events | confidential |

## MCP / A2A contracts

- MCP `semantic.get_measure(name, grain, filters, dry_run)`
- MCP `kyc.screen(names)`
- MCP `risk_model.score(borrower_id)`
- MCP `loan_system.set_credit_limit(borrower_id, amount, approvals, idempotency_key, dry_run)`

A collateral-valuation agent over the shared A2A contract would be the first peer.

**Tool identities (gateway allowlists):**

| Identity | Allowed tools |
|---|---|
| `mi-credit-reader` | `semantic.get_measure`, `kyc.screen`, `risk_model.score` |
| `mi-limit-booker` | `loan_system.set_credit_limit` |

## Stop conditions

- KYC is an unconditional edge after the planner; opaque ownership, a screening match or a screening outage stop the application before any memo
- financials only via registered measures with a dry-run plan check; no SQL surface exists
- any missing input (financials, risk score, policy) -> recommendation "refer", no approval path
- limits book only after two distinct approvers, the second a credit officer; the loan system re-checks
- memo figures and citations must match governed results, otherwise the deterministic template is used

## Failure playbook (five exits per node)

| Node | Success | Retry (backoff) | Compensate | Degrade | Escalate |
|---|---|---|---|---|---|
| `planner` | model plan with optional analyses | fallback deployment | n/a | models down / unparseable / required step omitted -> required steps enforced by the graph | n/a |
| `kyc` | UBOs >= 25% as of the application date identified and screened clear | gateway backoff on screening | n/a (read-only) | n/a (never skipped) | opaque owner, screening match or screening down -> stop, KYC team |
| `financials` | governed measures (dry-run plan checked, then executed) | gateway backoff | n/a (read-only) | semantic layer down / no gold rows -> financials missing -> refer | n/a |
| `risk` | PD and grade from the validated model | gateway backoff | n/a (read-only) | model endpoint down -> refer | n/a |
| `policy` | limits edition in force on the application date, cited | n/a (idempotent search) | n/a | retrieval down / edition not retrieved -> refer | n/a |
| `memo` | deterministic recommendation + model memo passing the numbers/citation critic | fallback deployment | n/a (no side effects) | models down or critic failure -> template memo | missing inputs -> refer; injected RM notes -> flagged to approvers |
| `first_approval` | registered approver approves | n/a | n/a | n/a | declined or unregistered approver -> stop |
| `second_approval` | a different person, a credit officer, approves | n/a | n/a | n/a | same person / not a credit officer / declined -> dual control refused |
| `book_limit` | loan system books the limit with both approvals | gateway backoff; idempotency key limit:<application> | limit reversal in the loan system (dual control again) | loan system down -> booking pending with approvals retained | loan system rejects approvals -> operations |

## Chaos scenarios (asserted in `tests/test_chaos.py`)

| Fault | Node | Expected exit | Invariant |
|---|---|---|---|
| `model` | `planner` | **degrade** | default plan still runs KYC; template memo; booked only with dual control |
| `retrieval` | `policy` | **degrade** | no limits policy -> refer; nothing booked |
| `sor:semantic` | `financials` | **degrade** | no governed financials -> refer; nothing booked |
| `sor:kyc` | `kyc` | **escalate** | screening outage stops the application; no memo |
| `jailbreak` | `memo` | **escalate** | injected RM notes neutralised and flagged; not in the memo; dual control unchanged |

## Evaluation

Golden set: `evals/golden.jsonl` · suite: `credit_memo.eval_suite:run_case` · run `python -m evals --project 15`

| Metric | Threshold | Current |
|---|---|---|
| task_success | >=0.95 | 1.00 |
| groundedness | >=0.95 | 1.00 |
| policy_violation_rate | <=0 | 0.00 |
| tool_error_rate | - | 0.03 |
| cost_per_task | <=0.002 | $0.00009 |

Cases: 18 · gate: **PASS**

## KPIs

| KPI | Target | How measured |
|---|---|---|
| Memo preparation time | < 1 hour from request to approver-ready memo | request -> first_approval interrupt timestamps |
| Memo figures traceable to governed measures | 100% | critic: every number in the memo appears in semantic-layer results; every figure cited |
| Limits booked without dual control or clear KYC | 0 | loan system audit: approvals distinct, second approver credit officer, KYC status clear |
| KYC bypass attempts honoured | 0 | planner exits 'omitted kyc' vs traces containing kyc |

## ROI sketch

Relationship managers and credit analysts spend much of a new-facility cycle gathering financials, tracing ownership and writing the memo. Automating the preparation shortens time to decision for borrowers and lets analysts handle more applications with consistent quality. Because figures come from governed measures and every number is cited, review effort drops and audit findings on data lineage fall. Credit risk is unchanged: KYC and dual control are enforced by the graph and the system of record. Costs are model usage and semantic-layer and screening integration.
