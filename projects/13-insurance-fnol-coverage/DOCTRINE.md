# Doctrine card: Insurance FNOL and coverage - scanned packet to adjuster-approved reserve

<!-- GENERATED from doctrine.yaml + evals/scores.json by `python -m shared.doctrine render`. Do not edit by hand. -->

> First notice of loss from a scanned packet. A Document-Intelligence-style extractor returns field-value pairs with confidence, and required fields below the floor go to a manual indexing queue instead of being guessed. The policy comes from policy admin over MCP. Coverage is decided by deterministic rules that must be grounded in the policy form wording retrieved as of the policy's form edition and for its state (amendatory endorsements). A deployed fraud model is called as an MCP tool, so the LLM never computes fraud. The proposal goes to an adjuster, within authority limits, before any reserve or payment. Claimant messages never mention internal review.

| Field | Value |
|---|---|
| Owner | Jagadish Meduri |
| Industry | Insurance (property & casualty claims) |
| Maturity | **Level 3**: agent proposes, adjuster disposes - extraction, coverage research and the proposal are automated, every reserve and payment needs an adjuster within authority limits |
| Next rung | straight-through processing for low-severity, low-band, clearly-covered claims under a per-state limit once leakage and reopen-rate KPIs hold for two quarters |
| Graph | `fnol.graph:build_graph` |

## Plane dependencies

| Plane | Dependency |
|---|---|
| Experience | claimant portal/email intake of scanned packets; adjuster workbench receives the interrupt payload (proposal, citations, internal fraud band) |
| Agent | LangGraph FNOL graph (intake -> policy -> [coverage || fraud] -> adjudicate -> human_approval -> finalize | queue) with checkpoints and interrupt() |
| Knowledge | policy-forms corpus on the shared ContextBuilder - edition validity (as-of the form edition date), state endorsements scoped by jurisdiction, SIU guide ACL'd to siu; deterministic rules must cite retrieved provisions |
| Data | Document Intelligence (mock), policy admin, fraud ML endpoint and claims system via MCP servers behind reader/writer gateways |

## Systems of record and semantic models

| System | Kind | Contract | Access |
|---|---|---|---|
| Document Intelligence (scanned packets) | document_store | `docintel.analyze_document(document_id) -> fields{value, confidence}` | read |
| Policy admin | mcp | `policy_admin.get_policy(policy_number) -> form, edition, jurisdiction, term, limit, deductible` | read |
| Fraud ML endpoint | api | `fraud_ml.score_claim(...) -> score, band, reasons, model_version (MCP-wrapped online endpoint)` | read |
| Claims system | mcp | `claims.open_claim, set_reserve, issue_payment, queue_document (writes, idempotent, approver required for money)` | write |

## Knowledge: retrieval corpora and ACL

| Corpus | Owner | ACL | Temporal validity | Refresh SLA | Sensitivity |
|---|---|---|---|---|---|
| policy-forms | Jagadish Meduri (product forms) | base HO3 forms everyone; state amendatory endorsements scoped to their jurisdiction; SIU-GUIDE-INT siu only | HO3 2019 edition (2019-06-01..2022-12-31) and 2023 edition; retrieved as-of the edition date on the policy, not the loss date | on form filing approval (new edition = new documents with validity; old editions kept) | internal |

The claim packet itself is per-request evidence (sanitised, never indexed).

## MCP / A2A contracts

- MCP `docintel.analyze_document(document_id)`
- MCP `policy_admin.get_policy(policy_number)`
- MCP `fraud_ml.score_claim(policy_number, loss_date, reported_date, amount)`
- MCP `claims.open_claim(fnol, idempotency_key, dry_run)`
- MCP `claims.set_reserve(claim_id, amount, approver, idempotency_key, dry_run)`
- MCP `claims.issue_payment(claim_id, amount, approver, idempotency_key, dry_run)`
- MCP `claims.queue_document(document_id, reason, idempotency_key, dry_run)`

SIU referral is an internal flag on the adjuster payload today; an SIU case agent over the shared A2A contract is the next peer.

**Tool identities (gateway allowlists):**

| Identity | Allowed tools |
|---|---|
| `mi-fnol-reader` | `docintel.analyze_document`, `policy_admin.get_policy`, `fraud_ml.score_claim` |
| `mi-claims-writer` | `claims.open_claim`, `claims.set_reserve`, `claims.issue_payment`, `claims.queue_document` |

## Stop conditions

- any required field (policy number, loss date, amount, description) below 0.85 OCR confidence -> manual indexing queue, nothing guessed
- instruction-like text in the packet -> queue for a human
- reserve and payment only after an adjuster approves, within that adjuster's authority; the agent identity is never an approver
- high fraud band -> SIU referral, payment held; the claimant hears only that an adjuster is handling it
- HITL timeout leaves the claim with the adjuster queue; it never pays

## Failure playbook (five exits per node)

| Node | Success | Retry (backoff) | Compensate | Degrade | Escalate |
|---|---|---|---|---|---|
| `intake` | all required fields >= 0.85 confidence; cause of loss known (field or model) | gateway backoff on extraction | n/a (read-only) | model down -> keyword cause classifier; extractor down -> queue | low confidence, missing packet or injected text -> manual indexing queue |
| `policy` | policy found and in force on the loss date | gateway backoff | n/a (read-only) | n/a | policy admin down or policy unknown -> queue; not in force -> adjuster decides (denial proposal) |
| `coverage` | rule decision whose provisions were retrieved for this edition and state, with citations | n/a (idempotent search, one attempt) | n/a | retrieval down or provision not retrieved -> coverage unknown, no payment proposed | n/a |
| `fraud` | model score, band and reasons from the ML endpoint | gateway backoff | n/a (read-only) | endpoint down -> no score, adjuster told to review manually | high band -> SIU referral, payment held |
| `adjudicate` | proposal (reserve, payment, citations) + adjuster note | fallback deployment | n/a (no side effects) | models down -> template note | n/a (always goes to the adjuster) |
| `human_approval` | adjuster approves or denies within authority | n/a | n/a | n/a | not an adjuster / over authority -> referred; SLA timeout -> stays queued, never pays |
| `finalize` | claim opened; reserve and payment written with approver + idempotency keys; claimant message passes the guard | gateway backoff; replays dedupe on fnol:/reserve:/pay: keys | reserve adjustment / payment void via the claims system (adjuster-initiated) | claims system down -> honest 'adjuster handling' message with FNOL reference; leaky draft -> template | n/a |
| `queue` | packet in the manual indexing queue with a reference | gateway backoff | n/a | claims system down -> reference only | n/a (the queue is the escalation) |

## Chaos scenarios (asserted in `tests/test_chaos.py`)

| Fault | Node | Expected exit | Invariant |
|---|---|---|---|
| `model` | `intake` | **degrade** | keyword classifier still finds theft; adjuster-approved payment unchanged |
| `retrieval` | `coverage` | **degrade** | coverage unknown; nothing paid |
| `sor:fraud_ml` | `fraud` | **degrade** | no score; adjuster note says review manually |
| `sor:policy_admin` | `policy` | **escalate** | packet queued; nothing paid |
| `jailbreak` | `intake` | **escalate** | injected packet text queued for a human; nothing paid; not echoed |

## Evaluation

Golden set: `evals/golden.jsonl` · suite: `fnol.eval_suite:run_case` · run `python -m evals --project 13`

| Metric | Threshold | Current |
|---|---|---|
| task_success | >=0.95 | 1.00 |
| groundedness | >=0.95 | 1.00 |
| policy_violation_rate | <=0 | 0.00 |
| tool_error_rate | - | 0.03 |
| cost_per_task | <=0.002 | $0.00005 |

Cases: 22 · gate: **PASS**

## KPIs

| KPI | Target | How measured |
|---|---|---|
| FNOL cycle time to adjuster-ready proposal | < 15 minutes for clean packets | packet received -> interrupt raised timestamps |
| Coverage decision accuracy | >= 98% agreement with adjuster disposition | proposal recommendation vs adjuster decision, sampled QA |
| Internal-review leakage to claimants | 0 messages | claimant channel scan for fraud/SIU/investigation language |
| Low-confidence packets guessed | 0 | queued vs processed packets with any required field < 0.85 confidence |

## ROI sketch

Adjusters spend a large share of FNOL time keying packets and looking up the right form edition and state endorsement. Automating extraction and coverage research moves that time to judgement, and deterministic, cited coverage decisions reduce leakage from applying the wrong edition. Payments stay adjuster-approved, so the upside comes from cycle time and consistency, not from removing controls. Costs are OCR and model usage and the integration of policy admin, claims and the fraud endpoint.
