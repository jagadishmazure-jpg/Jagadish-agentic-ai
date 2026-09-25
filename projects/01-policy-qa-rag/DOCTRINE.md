# Doctrine card: HR/IT policy Q&A (corrective RAG)

<!-- GENERATED from doctrine.yaml + evals/scores.json by `python -m shared.doctrine render`. Do not edit by hand. -->

> Employees get cited, policy-true answers from the HR/IT corpus they are allowed to see, as of the date that matters - or an honest "insufficient evidence" with a human contact.

| Field | Value |
|---|---|
| Owner | Jagadish Meduri |
| Industry | Cross-industry (employee services / internal knowledge) |
| Maturity | **Level 4**: lakehouse-grade knowledge + LLM with forced citations and a groundedness critic; read-only, no writes |
| Next rung | add a ticket-creation write tool (HITL) for unanswered questions once groundedness stays >= 0.95 on a 100-question set |
| Graph | `policy_qa.graph:build_graph` |

## Plane dependencies

| Plane | Dependency |
|---|---|
| Experience | Teams / intranet chat; Entra groups passed as the principal; answers cite chunk IDs the UI links to source documents |
| Agent | LangGraph corrective-RAG graph (rewrite -> retrieve -> grade -> bounded retry -> pack -> answer -> groundedness critic) |
| Knowledge | hr-it-policies knowledge product via shared ContextBuilder - hybrid BM25 + vector (RRF), heading-level chunks, ACL trim, temporal editions, sanitizer, budget packer |
| Data | none at runtime - policy documents are the system of record for this domain (HRIS facts would come via an MCP semantic tool in the next rung) |

## Systems of record and semantic models

| System | Kind | Contract | Access |
|---|---|---|---|
| HR/IT policy repository (SharePoint-like) | document_store | `hr-it-policies corpus (versioned documents -> chunks with ACL + validity)` | read |

## Knowledge: retrieval corpora and ACL

| Corpus | Owner | ACL | Temporal validity | Refresh SLA | Sensitivity |
|---|---|---|---|---|---|
| hr-it-policies | Jagadish Meduri (HR + IT knowledge product) | employees group for general policies; HR-COMP pay bands only hr / people-managers (trimmed before ranking) | valid_from / valid_to per edition; as_of from the question's business date (e.g. 2025 stipend edition) | 24h + event-driven on publish | internal; HR-COMP confidential |

## MCP / A2A contracts


Read-only knowledge agent; the corpus is served in-process by the shared ContextBuilder. The next rung exposes it as an MCP resource and adds a ticketing.create_ticket write for unanswered questions.

## Stop conditions

- at most 2 retrieval attempts (one corrective rewrite), then insufficient_evidence
- no answer is generated without graded-relevant evidence
- answers failing the groundedness critic (uncited or unsupported claims) are withheld
- context capped by an explicit token budget

## Failure playbook (five exits per node)

| Node | Success | Retry (backoff) | Compensate | Degrade | Escalate |
|---|---|---|---|---|---|
| `rewrite_query` | model rewrites the question into a search query | fallback deployment via breaker | n/a (no side effects) | deterministic lexical rewrite / synonym expansion when models are down | n/a |
| `retrieve` | hybrid hits, ACL-trimmed and valid on the as-of date, sanitized | corrective rewrite + one retry (graph edge) | n/a | injected spans neutralised and flagged; search outage -> insufficient_evidence (never answer from model memory) | page the knowledge owner if the index lags SLA (ops runbook) |
| `grade_chunks` | model grades relevance | fallback deployment | n/a | lexical overlap grader | n/a |
| `pack_context` | evidence packed within budget with source IDs | n/a | n/a | lowest-ranked chunks truncated/dropped to fit budget | n/a |
| `generate_answer` | cited answer from packed documents only | fallback deployment | n/a | extractive answer (cited verbatim sentences) when models are down | n/a |
| `check_groundedness` | every claim cited and supported by packed context | n/a - no argue-with-the-model loops | n/a | ungrounded draft withheld -> insufficient_evidence | n/a |
| `finalize` | Answer schema with citations and flagged injections | n/a | n/a | n/a | n/a |
| `insufficient_evidence` | honest fallback with HR / IT contact | n/a | n/a | n/a | human HR / IT channel named in the reply |

## Chaos scenarios (asserted in `tests/test_chaos.py`)

| Fault | Node | Expected exit | Invariant |
|---|---|---|---|
| `model` | `generate_answer` | **degrade** | still answered with a verbatim, cited sentence (HR-PTO-2) |
| `retrieval` | `retrieve` | **degrade** | insufficient_evidence citing search outage; no answer generated from model memory |
| `jailbreak` | `retrieve` | **degrade** | poisoned chunk sanitized and flagged; answer grounded, no admin-mode text |

## Evaluation

Golden set: `evals/golden.jsonl` · suite: `policy_qa.eval_suite:run_case` · run `python -m evals --project 01`

| Metric | Threshold | Current |
|---|---|---|
| task_success | >=0.9 | 1.00 |
| groundedness | >=0.95 | 1.00 |
| policy_violation_rate | <=0 | 0.00 |
| tool_error_rate | - | 0.00 |
| cost_per_task | <=0.002 | $0.00009 |

Cases: 13 · gate: **PASS**

## KPIs

| KPI | Target | How measured |
|---|---|---|
| Deflection of policy questions | >= 40% of HR/IT policy tickets | answered threads with no ticket filed within 3 days |
| Groundedness | >= 0.95 | citation coverage on the golden set + weekly sampled production answers |
| ACL leakage | 0 incidents | restricted-doc canary questions asked as non-privileged principals |

## ROI sketch

Value is HR/IT tickets deflected (fully loaded service-desk cost per ticket) plus employee time saved searching, minus index and token cost and knowledge-owner curation time. The honest insufficient-evidence exit prevents second contacts and wrong-policy escalations, which are subtracted from value rather than hidden.
