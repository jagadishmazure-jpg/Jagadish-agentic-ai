# `08-contract-review/tests/`: tests

Pytest suite for this project: behaviour of the graph and its guards, plus chaos tests driven
by the doctrine card. Shared fixtures such as `kill_model`, `kill_retrieval`, `kill_sor` and
`jailbreak`, and per-test fault isolation, come from the repo-root
[`conftest.py`](../../../conftest.py).

| File | What it does |
|---|---|
| [`conftest.py`](conftest.py) | Forces `LLM_PROVIDER=mock` for every test in the folder. |
| [`test_chaos.py`](test_chaos.py) | Doctrine-driven chaos tests. (3) |
| [`test_contract_review.py`](test_contract_review.py) | Segmentation and classification, evaluator feedback drives one revision, severity scoring and legal routing, conditional missing-clause findings, budget exhaustion then guardrail floor, unsupported findings dropped, prohibited redline blocked, precision/recall harness and gate. (8) |
| [`test_playbook.py`](test_playbook.py) | Playbook entry retrieved per clause type; senior fallbacks ACL-trimmed for the review agent. (2) |

Numbers in brackets are test counts from `pytest --collect-only` (13 in total).

## Run

```bash
pytest projects/08-contract-review                      # from the repo root
pytest projects/08-contract-review/tests/test_chaos.py -v
```

Tests run offline against the deterministic mock model; no API keys or network needed.

## Chaos scenarios (from `doctrine.yaml`)

`test_chaos.py` is parametrized from the card's `chaos:` list, so adding a scenario to the card
adds a test. Each fault must make the named node take the declared exit, and the invariant is
checked by `CHAOS_CHECKS` in [`contract_review/eval_suite.py`](../contract_review/eval_suite.py).

| Fault | Node | Exit | Invariant |
|---|---|---|---|
| `model` | `review` | degrade | rules-only review still flags liability, indemnity and termination and routes to legal |
| `retrieval` | `review` | degrade | playbook search down -> rules-only review with the same floor and route |
| `jailbreak` | `segment` | escalate | injected clause neutralised, injection flagged, routed to legal |
