# `credit_memo/`: credit memo with governed measures and dual control

The importable package for project 15. A planner model proposes analyses, but KYC is a
mandatory edge that no model (primary or fallback) can route around: beneficial owners are
computed by graph RAG over ownership edges as of the application date. Financial ratios come
only from a semantic layer of governed measures (dry-run plan first, no raw SQL), the PD score
from the existing risk model as a tool, and policy text from an as-of corpus. The memo is
drafted with citations and checked by a numbers/citation critic, then booked only after two
distinct approvers (the second a credit officer), which the loan system re-checks.

| File | What it does |
|---|---|
| [`__init__.py`](__init__.py) | Empty package marker. |
| [`demo.py`](demo.py) | CLI behind `run.py`: Northwind booked under maker/checker approval, same approver twice refused, a cheap fallback model trying to skip KYC for a trust-owned borrower (KYC still runs and stops), and an over-levered borrower with a decline recommendation; `--mermaid PATH`. |
| [`eval_suite.py`](eval_suite.py) | `run`, `run_case`, `request`, `chaos_scenario` and `CHAOS_CHECKS`. |
| [`graph.py`](graph.py) | `build_graph()` and `MemoState`. Nodes: `planner`, `kyc`, `financials`, `risk`, `policy`, `memo`, `first_approval`, `second_approval`, `book_limit`. Also `fast_track_responder`, a fallback model that tries to skip KYC, used in tests. |
| [`knowledge.py`](knowledge.py) | Credit policy corpus on `shared.context` with editions by effective date (as of the application date) and ACL; `band()` helper. |
| [`ownership.py`](ownership.py) | Graph RAG over ownership edges with `valid_from` / `valid_to`: `beneficial_owners(entity, as_of)` multiplies percentages along paths and sums per person; `evidence()` turns the edges used into citable `OWN::<edge id>` chunks. |
| [`semantic.py`](semantic.py) | Semantic layer over the credit mart: `get_measure(name, grain, filters, dry_run)` accepts only registered measures, grains and filter keys, requires `borrower_id`, and with `dry_run=True` returns the compiled plan instead of values. `SemanticError` on anything else. |
| [`sor.py`](sor.py) | MCP servers (semantic layer, KYC screening, risk model, loan system) and the gateways. |
| [`systems.py`](systems.py) | Mock KYC screening, PD/rating model and loan system; `seed_systems()`. |

## Graph

```
planner -> kyc (ownership graph RAG as-of + screening; mandatory)
  -> [financials (semantic layer: dry-run, then execute) || risk (PD model tool) || policy (RAG as-of)]
  -> memo (deterministic recommendation + cited draft + critic)
  -> first_approval -> second_approval (distinct people; second is a credit officer) -> book_limit
```

## Design notes

- The critic replaces invented numbers with the governed values.
- Dual control is enforced twice: in the graph and in the loan system.
- Booking is idempotent on replay.

## Run

```bash
python projects/15-banking-credit-memo/run.py                    # demo (offline, mock LLM)
python projects/15-banking-credit-memo/run.py --mermaid projects/15-banking-credit-memo/graph.mmd  # also refresh the Mermaid diagram
pytest projects/15-banking-credit-memo                           # tests
python -m evals --project 15                # golden-set eval
CHAOS_FAULTS=model python projects/15-banking-credit-memo/run.py   # demo with every model deployment down
```

See the [project README](../README.md) for the business problem and design trade-offs, and [`DOCTRINE.md`](../DOCTRINE.md) for the five-exit table per node.
