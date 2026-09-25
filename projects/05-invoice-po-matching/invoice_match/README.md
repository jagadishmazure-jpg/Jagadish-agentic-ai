# `invoice_match/`: invoice extraction and three-way match

The importable package for project 05. It extracts a vendor invoice into a strict schema
(retrying once with the validation errors fed back), fetches the purchase order, goods receipts
and invoiced quantities from the ERP over MCP, and applies deterministic three-way match rules.
Clean invoices are posted for payment idempotently; everything else becomes typed exceptions
plus a drafted note for the AP exceptions queue.

| File | What it does |
|---|---|
| [`__init__.py`](__init__.py) | Package docstring. |
| [`demo.py`](demo.py) | CLI behind `run.py`; `--mermaid PATH`. |
| [`erp.py`](erp.py) | `MockERP` with typed errors: business (`PONotFoundError`, `POClosedError`) versus transient (`ERPUnavailableError`, retried by the node's `RetryPolicy`); idempotent invoice posting; `seed_erp()`. |
| [`eval_suite.py`](eval_suite.py) | `run_case`, `chaos_scenario` and `CHAOS_CHECKS`. |
| [`graph.py`](graph.py) | `build_graph()` and `InvoiceState`. Nodes: `extract`, `extraction_failed`, `fetch_erp`, `three_way_match`, `approve_for_payment`, `draft_exception_note`. |
| [`invoices.py`](invoices.py) | Text-based mock invoices (as if from an email body or text layer). |
| [`llm.py`](llm.py) | Extraction and exception-note prompts and `regex_extract`, a deterministic stand-in (strict layout first, lenient layout after feedback). |
| [`matching.py`](matching.py) | Pure functions: `arithmetic_errors` and `three_way_match` (price tolerance, quantity against receipts, unknown lines, ...). |
| [`schema.py`](schema.py) | `InvoiceLine`, `Invoice`, `MatchException`, `MatchResult`. |
| [`sor.py`](sor.py) | ERP behind MCP: `ErpBackend`, the `PurchaseOrder` payload contract and `build_gateway()`; business errors cross the wire as typed envelopes and are re-raised as the same exception types. |
| [`worker.py`](worker.py) | `process()`: the durable boundary around one run. If the ERP is still down after the node's retries, the invoice is parked for redelivery instead of being misfiled as an exception. |

## Graph

```
extract --invalid (attempt < 2, errors fed back)--> extract
        --invalid after 2 attempts--> draft_exception_note
        --valid--> fetch_erp (RetryPolicy on transient ERP errors) --> three_way_match
                      --clean--> approve_for_payment (idempotent post)
                      --exceptions--> draft_exception_note -> AP exceptions queue
```

## Design notes

- Transient and business errors are separate types, so an ERP outage is retried and then
  propagated, never turned into a "PO not found" exception.
- The model only extracts and writes notes; validation and matching are the gate. With the model
  down, extraction degrades to the template parser and the note to a template.
- Suspected injected instructions in the invoice text force AP review (`SUSPICIOUS_CONTENT`).

## Run

```bash
python projects/05-invoice-po-matching/run.py                    # demo (offline, mock LLM)
python projects/05-invoice-po-matching/run.py --mermaid projects/05-invoice-po-matching/graph.mmd  # also refresh the Mermaid diagram
pytest projects/05-invoice-po-matching                           # tests
python -m evals --project 05                # golden-set eval
CHAOS_FAULTS=model python projects/05-invoice-po-matching/run.py   # demo with every model deployment down
```

See the [project README](../README.md) for the business problem and design trade-offs, and [`DOCTRINE.md`](../DOCTRINE.md) for the five-exit table per node.
