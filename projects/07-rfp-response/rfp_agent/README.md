# `rfp_agent/`: planner, section subgraphs, critic and compliance

The importable package for project 07. A planner splits an RFP into sections, and each section
is processed by a compiled worker subgraph launched with `Send`. Inside the subgraph each
question is drafted only from the approved answer library, checked by a critic (required
facets, valid citations) and revised within a budget, or handed to a subject-matter expert.
A compliance pass then strips banned claims and flags export-control terms for legal review.

| File | What it does |
|---|---|
| [`__init__.py`](__init__.py) | Package docstring. |
| [`demo.py`](demo.py) | CLI behind `run.py`: answers the sample RFP; `--mermaid PATH`. |
| [`eval_suite.py`](eval_suite.py) | `run_case`, `chaos_scenario` and `CHAOS_CHECKS`. |
| [`graph.py`](graph.py) | `build_graph()` (parent: `plan`, `section_worker`, `compliance`, `assemble`) and `build_section_graph()` (subgraph: `next_question`, `retrieve`, `draft`, `critique`, `accept`, `needs_sme`). Models `Question`, `Section`, `SectionState`, `RfpState`, `ResponseDoc`. |
| [`knowledge.py`](knowledge.py) | Approved answer entries, the sample RFP, and `parse_rfp`, the deterministic planner fallback (`## Section` headers and `Qn.` lines). |
| [`library.py`](library.py) | The answer library as a knowledge product on `shared.context`: ACL keeps deal-desk pricing out of presales drafts, and editions follow the submission date. `search()` returns sanitised entries or raises a typed error. |
| [`llm.py`](llm.py) | Planner and drafter prompts; `mock_draft` and `mock_responder`. |
| [`rules.py`](rules.py) | Pure functions: `retrieve`, `required_facets`, `critique` and `compliance_scan` (returns cleaned text, banned claims removed, export-control hits). |

## Graph

```
Parent:   plan --Send per section--> section_worker (compiled subgraph) --> compliance --> assemble
Subgraph: next_question -> retrieve -> draft -> critique
              pass -> accept -> next_question
              fail & budget left -> draft (with feedback)
              fail & (no KB hit | budget spent) -> needs_sme -> next_question
```

## Design notes

- A library outage sends questions to SMEs; answers never come from model memory.
- With the model down, the planner falls back to `parse_rfp` and the drafter to verbatim cited
  library sentences.

## Run

```bash
python projects/07-rfp-response/run.py                    # demo (offline, mock LLM)
python projects/07-rfp-response/run.py --mermaid projects/07-rfp-response/graph.mmd  # also refresh the Mermaid diagram
pytest projects/07-rfp-response                           # tests
python -m evals --project 07                # golden-set eval
CHAOS_FAULTS=model python projects/07-rfp-response/run.py   # demo with every model deployment down
```

See the [project README](../README.md) for the business problem and design trade-offs, and [`DOCTRINE.md`](../DOCTRINE.md) for the five-exit table per node.
