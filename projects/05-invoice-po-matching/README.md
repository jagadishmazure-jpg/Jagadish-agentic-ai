# 05 · Invoice ↔ PO Matching

> **Status:** planned (not built yet)

Accounts payable teams manually match invoices to purchase orders and goods receipts (3-way match). The agent extracts invoice fields, matches line items with tolerances, auto-approves clean matches and routes exceptions (price/quantity variance, missing PO) to AP clerks.

**Graph pattern it teaches:** Deterministic pipeline with LLM extraction at the edge, plus an exception-handling subgraph and HITL for mismatches.

**Planned components:**

- LLM-based invoice field extraction into a Pydantic schema, validated by rules
- 3-way match engine (PO, receipt, invoice) with configurable tolerances
- Exception subgraph with reason codes
- `interrupt()` for clerk review of variances
- Mock ERP (SAP/Oracle-like) posting API with idempotency
- Audit trail per invoice

Like every project in this repo, it will run offline with the shared mock LLM (`shared.llm.get_llm`) and optionally against Azure OpenAI / OpenAI via env vars.
