# `contract_review/`: evaluator-optimizer contract review

The importable package for project 08. A contract is segmented and each clause classified; a
reviewer model drafts findings and redlines, and a deterministic playbook evaluator compares
the draft with the rule-based floor and feeds back what is missing or wrong, for up to three
iterations. Guardrails then enforce the playbook floor and block prohibited redlines, and the
result is scored and routed: legal review when any finding is high or critical (or an
injection is suspected), otherwise the business owner. An offline precision/recall harness
gates changes.

| File | What it does |
|---|---|
| [`__init__.py`](__init__.py) | Package docstring. |
| [`contracts.py`](contracts.py) | Sample contract for the demo and the labelled evaluation set loaded from `evals/golden.jsonl`. Some cases are deliberately hard for the playbook rules. |
| [`demo.py`](demo.py) | CLI behind `run.py`: reviews the sample contract; `--mermaid PATH`. |
| [`eval_suite.py`](eval_suite.py) | `run_case` (success = predicted `{clause_type: severity}` equals the gold labels, plus route when given), `chaos_scenario` and `CHAOS_CHECKS`. |
| [`evaluation.py`](evaluation.py) | Precision/recall harness over flagged risks: `run_eval`, `gate` (pass/fail for CI) and `format_report`; severity accuracy on true positives. |
| [`graph.py`](graph.py) | `build_graph()` and models `Finding`, `ReviewReport`, `ReviewState`. Nodes: `segment`, `classify_clauses`, `review`, `evaluate`, `guardrails`, `score_and_route`. |
| [`library.py`](library.py) | Clause library: classification keywords, red flags with severity, standard positions and approved redline language. |
| [`llm.py`](llm.py) | Classification and review prompts; `mock_review` behaves like a plausible first-pass model (rates everything medium, forgets missing clauses) and follows evaluator feedback on revision. |
| [`playbook.py`](playbook.py) | Playbook text on `shared.context`, retrieved per clause type; senior-counsel fallback positions are ACL-restricted to `legal-senior`. `playbook_context()`. |
| [`rules.py`](rules.py) | Deterministic engine: `segment`, `keyword_type`, `expected_findings` (rule floor), `evaluate` (feedback items), `violates_guardrail`, `score`. |

## Graph

```
segment -> classify_clauses -> review (optimizer) -> evaluate (playbook evaluator)
    feedback & iterations < 3 -> review (revise with feedback)
    clean or budget spent     -> guardrails -> score_and_route -> END
```

## Design notes

- The rules engine and guardrails are the control; the model's job is wording and judgement
  within them. With the model down, a keyword classifier and a rules-only review take over.
- Suspected injected instructions in contract text force legal review.
- Task success is intentionally below 1.00 on the golden set (see [`../evals`](../evals/README.md)).

## Run

```bash
python projects/08-contract-review/run.py                    # demo (offline, mock LLM)
python projects/08-contract-review/run.py --mermaid projects/08-contract-review/graph.mmd  # also refresh the Mermaid diagram
pytest projects/08-contract-review                           # tests
python -m evals --project 08                # golden-set eval
CHAOS_FAULTS=model python projects/08-contract-review/run.py   # demo with every model deployment down
```

See the [project README](../README.md) for the business problem and design trade-offs, and [`DOCTRINE.md`](../DOCTRINE.md) for the five-exit table per node.
