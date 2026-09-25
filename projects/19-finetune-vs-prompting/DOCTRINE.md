# Doctrine card: Fine-tuning vs prompting - mortgage document classification with a promotion gate

<!-- GENERATED from doctrine.yaml + evals/scores.json by `python -m shared.doctrine render`. Do not edit by hand. -->

> Loan processors spend time naming and filing every uploaded page of a loan file. This project classifies a document's first page into one of ten mortgage document types and decides, with evidence, whether a fine-tuned model should replace the prompted base model. A dataset builder scrubs borrower PII, removes duplicates, splits by loan file and checks for leakage before writing chat-format JSONL. An offline fine-tuning path trains a small classification head on CPU. A comparison harness runs both variants through the shared eval harness and reports accuracy, macro-F1, latency and a token proxy for cost. A model registry promotes the fine-tuned model only if it beats the incumbent on the validation split, and supports rollback. The serving graph files confident documents in the LOS and queues everything else for a processor. An optional Azure OpenAI fine-tuning script consumes the same JSONL and is dry-run by default.

| Field | Value |
|---|---|
| Owner | Jagadish Meduri |
| Industry | Banking (mortgage origination, loan processing) |
| Maturity | **Level 3**: champion model files documents autonomously above a confidence floor; promotion is gated on validation metrics and every non-confident, injected or unclassifiable page goes to a processor |
| Next rung | weekly re-label sample from processors feeds a drift monitor that triggers rollback automatically, and a hosted Azure OpenAI fine-tune is evaluated through the same harness before it can become champion |
| Graph | `finetune_lab.graph:build_graph` |

## Plane dependencies

| Plane | Dependency |
|---|---|
| Experience | loan processor e-folder view (filed type + confidence) and a document review queue |
| Agent | LangGraph serving graph (intake -> classify -> file_document | human_review) plus the offline train -> compare -> gate -> promote/rollback lifecycle |
| Knowledge | none at runtime; the label taxonomy and rubric are versioned artifacts in the model registry |
| Data | loan origination system (LOS) document index via MCP; model registry (versioned artifacts, champion pointer) |

## Systems of record and semantic models

| System | Kind | Contract | Access |
|---|---|---|---|
| LOS document index | mcp | `los.file_document(loan_id, doc_id, doc_type, confidence, model_version, idempotency_key, dry_run); los.queue_review(loan_id, doc_id, reason, idempotency_key, dry_run)` | write |
| Model registry | document_store | `registry.json entries {version, kind, sha256, dataset_sha256, metrics, stage} + artifacts/<version>.json` | read |

## Knowledge: retrieval corpora and ACL


No retrieval. The input is the uploaded page itself, treated as untrusted (PII-scrubbed and injection-checked before any model sees it). The label rubric lives in the registered prompt artifact.

## MCP / A2A contracts

- MCP `los.file_document(loan_id, doc_id, doc_type, confidence, model_version, idempotency_key, dry_run)`
- MCP `los.queue_review(loan_id, doc_id, reason, idempotency_key, dry_run)`

Gateway identity mi-doc-classifier can only file or queue documents; page text never crosses the MCP boundary, only the type, confidence and model version.

**Tool identities (gateway allowlists):**

| Identity | Allowed tools |
|---|---|
| `mi-doc-classifier` | `los.file_document`, `los.queue_review` |

## Stop conditions

- confidence < 0.55 or label 'unknown' -> processor review queue, never a guessed type
- suspected prompt injection in the page text -> processor review, never auto-filed
- all model deployments down -> processor review
- a candidate model is promoted only if it beats the champion on validation macro-F1 by >= 0.02 with no accuracy loss and no label losing more than 0.10 F1
- one LOS write per document (idempotency key classify:<doc_id>)

## Failure playbook (five exits per node)

| Node | Success | Retry (backoff) | Compensate | Degrade | Escalate |
|---|---|---|---|---|---|
| `intake` | PII replaced with typed placeholders before any model call | n/a (deterministic) | n/a | n/a | suspected prompt injection -> processor review |
| `classify` | registry champion returns a label and confidence | prompted baseline answers when the fine-tuned deployment is down (fallback chain + breakers underneath) | n/a (no side effects) | champion artifact fails its hash check or deployment down -> prompted baseline; every model down -> processor review | low confidence or 'unknown' -> processor review |
| `file_document` | document filed in the LOS under the predicted type (idempotent on doc id) | gateway backoff on transient LOS errors | n/a (replay returns the same filing) | LOS outage -> filing parked in the outbox with its idempotency key | n/a |
| `human_review` | document queued for a processor with the reason and the model's suggestion | gateway backoff on transient LOS errors | n/a (replay returns the same queue item) | LOS outage -> queue item parked in the outbox | this node is the escalation path |

## Chaos scenarios (asserted in `tests/test_chaos.py`)

| Fault | Node | Expected exit | Invariant |
|---|---|---|---|
| `model` | `classify` | **degrade** | every model down -> processor review with 'classifier unavailable', no guessed type |
| `model:finetuned` | `classify` | **degrade** | fine-tuned deployment down -> prompted baseline files the W-2 and records its version |
| `sor:los` | `file_document` | **degrade** | type kept, filing parked in the outbox with idempotency key classify:<doc_id> |
| `jailbreak` | `intake` | **escalate** | page with injected instructions goes to processor review, not the requested type |

## Evaluation

Golden set: `evals/golden.jsonl` · suite: `finetune_lab.eval_suite:run_case` · run `python -m evals --project 19`

| Metric | Threshold | Current |
|---|---|---|
| task_success | >=0.9 | 1.00 |
| groundedness | - | n/a |
| policy_violation_rate | <=0 | 0.00 |
| tool_error_rate | <=0.05 | 0.00 |
| cost_per_task | <=0.002 | $0.00000 |

Cases: 14 · gate: **PASS**

## KPIs

| KPI | Target | How measured |
|---|---|---|
| Auto-file precision | >= 98% of auto-filed documents keep their type after processor QC | filed type vs processor QC sample |
| Auto-file rate | >= 80% of uploaded pages filed without a processor | filed / (filed + queued) per week |
| Borrower PII in training files | 0 | validator + planted-value test on every dataset build |
| Promotions without a validation win | 0 | registry events: promoted entries all passed the gate |

## ROI sketch

Value is processor minutes saved per loan file on stacking and naming documents, plus fewer conditions raised late because a document was misfiled. The fine-tuned model also sends about a tenth of the prompt tokens per call. Costs are labelling and QC time, training runs, hosting a fine-tuned deployment (billed hourly while deployed) and the processor queue created by low-confidence pages, which is tracked rather than hidden.
