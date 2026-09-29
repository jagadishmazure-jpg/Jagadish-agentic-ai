# Doctrine card: Multi-agent orchestration patterns, compared on one loan-exception task

<!-- GENERATED from doctrine.yaml + evals/scores.json by `python -m shared.doctrine render`. Do not edit by hand. -->

> One realistic task (resolve a mortgage underwriting exception: research the loan file, analyse ratios, check the credit policy in force, draft a cited memo) solved by eight orchestration patterns as LangGraph graphs: sequential, concurrent fan-out/fan-in, supervisor, hierarchical teams, handoff swarm, moderated group chat/debate, magentic (task and progress ledgers) and blackboard. A common harness enforces budgets, loop and ping-pong detection, route validation, termination and tracing, and a comparison runner scores every pattern on the same golden set and under injected faults.

| Field | Value |
|---|---|
| Owner | Jagadish Meduri |
| Industry | Banking (mortgage underwriting exceptions) |
| Maturity | **Level 3**: every pattern shares least-privilege MCP identities, as-of policy retrieval with ACL, a deterministic critic, budgets and a human gate for referrals; comparison numbers are regenerated from runs and gated in CI |
| Next rung | run the comparison against a real model deployment on a larger sampled set and promote the chosen pattern behind the control-plane registry (project 12) with per-pattern kill switches |
| Graph | `orchestration_lab.graph:build_graph` |

## Plane dependencies

| Plane | Dependency |
|---|---|
| Experience | underwriter exception ticket in; filed memo on the loan; credit officer approval step for referrals (interrupt payload with reason, citations and memo) |
| Agent | arena LangGraph graph (intake -> one of eight pattern graphs -> human_gate -> finalize); each pattern is its own graph over shared worker agents inside a common harness (budgets, loop detection, route validation, OTel spans per agent turn) |
| Knowledge | credit-policy corpus through the shared context builder (hybrid retrieval, ACL by principal, as-of the application date); restricted committee minutes trimmed before ranking |
| Data | loan origination system and credit bureau through MCP servers with one scoped gateway per identity; the memo is filed by the orchestrator identity only (idempotent, dry-run default) |

## Systems of record and semantic models

| System | Kind | Contract | Access |
|---|---|---|---|
| Loan origination system | mcp | `loan_system.get_loan_file, loan_system.get_appraisal (read); loan_system.file_exception_memo (write, idempotent)` | read_write |
| Credit bureau | mcp | `credit_bureau.get_credit_summary (read)` | read |

## Knowledge: retrieval corpora and ACL

| Corpus | Owner | ACL | Temporal validity | Refresh SLA | Sensitivity |
|---|---|---|---|---|---|
| credit-policy | credit-policy | underwriting group; committee minutes restricted to credit-committee | DTI rule has 2025 and 2026 editions; retrieval as-of the application date | on credit policy committee approval | internal |

Limits come from the rule registry keyed by the cited policy id, never from model prose; the policy agent's topic mapping is validated against the retrieved ids.

## MCP / A2A contracts

- MCP `loan_system.get_loan_file(loan_id) -> LoanFile (borrower note is untrusted text)`
- MCP `loan_system.get_appraisal(loan_id) -> {status, value}`
- MCP `loan_system.file_exception_memo(loan_id, decision, memo, idempotency_key, dry_run) -> {memo_id}`
- MCP `credit_bureau.get_credit_summary(loan_id) -> {fico}`

Workers are in-process functions behind Harness.turn; any of them could become an A2A agent (project 12) without changing the pattern graphs.

**Tool identities (gateway allowlists):**

| Identity | Allowed tools |
|---|---|
| `mi-exception-researcher` | `loan_system.get_loan_file`, `loan_system.get_appraisal`, `credit_bureau.get_credit_summary` |
| `mi-exception-analyst` | `loan_system.get_loan_file`, `loan_system.get_appraisal`, `credit_bureau.get_credit_summary` |
| `mi-exception-filer` | `loan_system.file_exception_memo` |

## Stop conditions

- harness budgets per run (30 agent turns, 40 LLM calls, 40k estimated tokens) -> budget_exhausted referral
- loop control per pattern - one revision (supervisor, hierarchical), ping-pong A-B-A-B-A-B (swarm), repeated review issues (group chat, blackboard), stall counter with at most one replan (magentic), 16 speaker rounds (group chat)
- every model-proposed route, handoff or speaker is validated against the registry and prerequisites; a bad target is rejected (fallback or one re-ask), never executed
- only a reviewer-passed memo counts as completed; every other stop is a referral to the human gate, never a guessed decision
- no agent can file; filing is the orchestrator identity in finalize, idempotent per loan, pattern and decision

## Failure playbook (five exits per node)

| Node | Success | Retry (backoff) | Compensate | Degrade | Escalate |
|---|---|---|---|---|---|
| `intake` | ticket loaded for a known loan and a registered pattern | n/a (local ticket read) | n/a | n/a | unknown loan or pattern -> rejected, nothing runs |
| `sequential` | one pass researcher -> analyst -> policy -> drafter -> reviewer passes | gateway backoff on SoR reads only | n/a (read-only until finalize) | model down -> each worker's deterministic path | any worker failure or a failed review (no loop back) -> referral |
| `concurrent` | researcher, policy and analyst fan out in one super-step; join; draft; review passes | gateway backoff on SoR reads only | n/a (read-only until finalize) | model down -> deterministic worker paths | a failed branch or failed review -> referral |
| `supervisor` | validated routes until the reviewer passes the memo | one retry per failed worker; one revision after a failed review | n/a (read-only until finalize) | invalid/unparseable route or model down -> deterministic plan | worker fails twice, second review failure or budget -> referral |
| `hierarchical` | top supervisor runs evidence and policy teams in parallel, then the decision team; review passes | one revision inside the decision team | n/a (read-only until finalize) | invalid top or team-lead route -> deterministic team plan | a failed member ends its team and the top supervisor refers the file |
| `swarm` | peer handoffs until the reviewer hands off to END with a passed review | an invalid handoff target gets one re-ask of the sending agent | n/a (read-only until finalize) | model down -> deterministic handoff choice | second bad handoff, ping-pong, worker down or budget -> referral |
| `group_chat` | moderator-led chat reaches consensus, drafter writes, reviewer passes | n/a (moderator re-selects speakers) | n/a (read-only until finalize) | invalid speaker or model down -> deterministic speaker policy | max rounds, repeated review issues, missing evidence worker or budget -> referral |
| `magentic` | progress ledger reports the request satisfied after a passed review | stall or failed assignee -> replan (at most once) | n/a (read-only until finalize) | invalid ledger or speaker -> deterministic ledger; failed worker's task moves to another capable agent | stalled after replan, no capable agent for a task, or budget -> referral |
| `blackboard` | control fires eligible sources until the review on the board passes | a failed review makes the drafter eligible again | n/a (read-only until finalize) | failed analyst -> researcher's ratio calculator posts the analysis | no eligible source, repeated review issues or budget -> referral |
| `human_gate` | no referral, or a credit officer decides the referred file | n/a | n/a | n/a | is the human gate (interrupt with reason, citations and memo) |
| `finalize` | completed memo filed once (idempotency key per loan, pattern and decision) | gateway backoff on the filing call | n/a (filing is a record, not a funding action) | n/a | loan system down at filing -> memo not filed, recorded for the underwriter |

## Chaos scenarios (asserted in `tests/test_chaos.py`)

| Fault | Node | Expected exit | Invariant |
|---|---|---|---|
| `model` | `supervisor` | **degrade** | every worker and the router take their deterministic path; zero LLM calls; correct decision filed once |
| `sor:loan_system` | `swarm` | **escalate** | researcher cannot read the file -> swarm refers the case; nothing filed |
| `retrieval` | `magentic` | **escalate** | policy agent fails; replan finds no capable agent for rules -> referral; nothing filed |
| `jailbreak` | `group_chat` | **degrade** | injected borrower note neutralised by the gateway; decision unchanged; no injected text in memo or trace |

## Evaluation

Golden set: `evals/golden.jsonl` · suite: `orchestration_lab.eval_suite:run_case` · run `python -m evals --project 21`

| Metric | Threshold | Current |
|---|---|---|
| task_success | >=0.95 | 1.00 |
| groundedness | >=0.95 | 1.00 |
| policy_violation_rate | <=0 | 0.00 |
| tool_error_rate | - | 0.00 |
| cost_per_task | <=0.003 | $0.00047 |

Cases: 24 · gate: **PASS**

## KPIs

| KPI | Target | How measured |
|---|---|---|
| Exception memos accepted without rework | >= 90% of completed memos | senior underwriter QC outcome per filed memo |
| Wrong exception decisions filed | 0 | QC overturns where the filed decision contradicts the policy edition in force |
| Referral precision | >= 80% of referrals need a committee or officer decision | credit officer disposition of human_gate referrals |
| Cost per resolved exception | tracked per pattern; alert on +25% week over week | LLM calls and tokens per case from agent spans |

## ROI sketch

Underwriters spend time assembling the same four inputs for every exception ticket. A pattern that gets the memo right first time saves that assembly and review time; the comparison shows which pattern buys the needed quality at the lowest model cost and latency, and which ones fail safely when a worker is down or loops. Cost is model tokens (tracked per pattern) and officer time on referrals. The main risk is a wrong decision filed, which the critic, the policy-as-code check and the human gate are there to prevent.
