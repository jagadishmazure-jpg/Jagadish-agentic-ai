# Doctrine card: Invoice / PO three-way matching (AP automation)

<!-- GENERATED from doctrine.yaml + evals/scores.json by `python -m shared.doctrine render`. Do not edit by hand. -->

> Vendor invoices are extracted into a strict schema and three-way matched against the ERP (PO, goods receipts, invoices already posted). Clean invoices are posted once and only once. Every other invoice goes to the AP exceptions queue with typed reasons and a drafted note.

| Field | Value |
|---|---|
| Owner | Jagadish Meduri |
| Industry | Finance operations / accounts payable (manufacturing, distribution) |
| Maturity | **Level 4**: governed ERP reads + one idempotent write behind MCP, deterministic match as the control, typed exceptions |
| Next rung | vendor-master semantic model + A2A hand-off to a vendor-communication agent for credit-note requests |
| Graph | `invoice_match.graph:build_graph` |

## Plane dependencies

| Plane | Dependency |
|---|---|
| Experience | AP mailbox / vendor portal intake; AP exceptions queue shows the typed exception list and drafted note |
| Agent | LangGraph pipeline (extract with feedback retry -> fetch_erp with RetryPolicy -> deterministic three-way match -> post or exception note) |
| Knowledge | none at runtime (tolerances and matching rules are code, versioned and tested) |
| Data | ERP purchasing / receiving / AP via MCP (SAP-like), the system of record for POs, receipts and postings |

## Systems of record and semantic models

| System | Kind | Contract | Access |
|---|---|---|---|
| ERP (SAP-like purchasing, receiving, AP) | mcp | `erp.get_purchase_order, erp.get_goods_receipts, erp.get_invoiced_quantities, erp.is_invoice_posted, erp.post_invoice` | read_write |

## Knowledge: retrieval corpora and ACL


The invoice document itself is the only unstructured input and is treated as untrusted data (sanitised; instruction-like text forces AP review).

## MCP / A2A contracts

- MCP `erp.get_purchase_order(po_number) -> PurchaseOrder | PONotFoundError | POClosedError`
- MCP `erp.get_goods_receipts(po_number) -> {sku: qty}`
- MCP `erp.get_invoiced_quantities(po_number) -> {sku: qty}`
- MCP `erp.is_invoice_posted(invoice_number) -> {posted}`
- MCP `erp.post_invoice(invoice, idempotency_key=ap:<invoice no>, dry_run) -> {document_id}`

Identity mi-ap-invoice-matcher. Outages are retryable envelopes (node RetryPolicy, x3); business errors are typed and never retried.

**Tool identities (gateway allowlists):**

| Identity | Allowed tools |
|---|---|
| `mi-ap-invoice-matcher` | `erp.get_purchase_order`, `erp.get_goods_receipts`, `erp.get_invoiced_quantities`, `erp.is_invoice_posted`, `erp.post_invoice` |

## Stop conditions

- at most 2 extraction attempts (second one gets validation feedback)
- fetch_erp retried at most 3 times on outage, then the invoice is parked for redelivery
- post_invoice only after a clean deterministic three-way match, idempotent on invoice number
- any suspicious content or exception -> AP exceptions queue, never auto-approved

## Failure playbook (five exits per node)

| Node | Success | Retry (backoff) | Compensate | Degrade | Escalate |
|---|---|---|---|---|---|
| `extract` | schema-valid invoice whose arithmetic checks pass | second attempt with validation feedback; fallback model deployment | n/a | all models down -> deterministic template parser (validation + match still gate payment) | instruction-like text -> SUSPICIOUS_CONTENT exception for AP review |
| `extraction_failed` | EXTRACTION_FAILED exception recorded | n/a | n/a | n/a | manual keying in the AP exceptions queue |
| `fetch_erp` | PO, receipts and invoiced quantities fetched via MCP (schema-valid) | RetryPolicy x3 with backoff on ERP outage; then the worker parks the invoice for redelivery | n/a (read-only) | n/a - never guesses ERP state | PO not found / closed / duplicate -> typed exception to AP |
| `three_way_match` | no variances within tolerance | n/a (deterministic) | n/a | n/a | variances -> typed exceptions |
| `approve_for_payment` | invoice posted once (idempotency key ap:<invoice no>) | replay returns the original document (idempotent) | reversal document by AP if a posted invoice is later disputed (manual, audited) | n/a | n/a |
| `draft_exception_note` | note mentions every exception code and a next step | fallback deployment | n/a | template note when models are down or the draft omits a code | routed to ap_exceptions_queue |

## Chaos scenarios (asserted in `tests/test_chaos.py`)

| Fault | Node | Expected exit | Invariant |
|---|---|---|---|
| `model` | `extract` | **degrade** | clean invoice still approved via template parser; posted exactly once |
| `sor` | `fetch_erp` | **retry** | ERP outage retried then parked for redelivery; nothing posted, not misfiled as exception |
| `jailbreak` | `extract` | **escalate** | invoice with injected instruction goes to AP exceptions; nothing posted |

## Evaluation

Golden set: `evals/golden.jsonl` · suite: `invoice_match.eval_suite:run_case` · run `python -m evals --project 05`

| Metric | Threshold | Current |
|---|---|---|
| task_success | >=0.9 | 1.00 |
| groundedness | - | n/a |
| policy_violation_rate | <=0 | 0.00 |
| tool_error_rate | - | 0.14 |
| cost_per_task | <=0.002 | $0.00017 |

Cases: 12 · gate: **PASS**

## KPIs

| KPI | Target | How measured |
|---|---|---|
| Touchless rate | >= 60% of PO-backed invoices | approved_for_payment without human touch / all PO invoices |
| Duplicate or over-payment | 0 | post_invoice calls per invoice number; audit sample |
| Exception cycle time | -40% vs baseline | exception queued -> resolved |

## ROI sketch

Value is AP clerk minutes per invoice saved on clean matches, plus early-payment discounts captured, plus duplicate payments prevented. Subtract token and OCR cost and the review time spent on exceptions, which the typed reasons and drafted notes shorten but do not remove.
