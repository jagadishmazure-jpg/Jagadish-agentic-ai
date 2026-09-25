# `01-policy-qa-rag/tests/`: tests

Pytest suite for this project: behaviour of the graph and its guards, plus chaos tests driven
by the doctrine card. Shared fixtures such as `kill_model`, `kill_retrieval`, `kill_sor` and
`jailbreak`, and per-test fault isolation, come from the repo-root
[`conftest.py`](../../../conftest.py).

| File | What it does |
|---|---|
| [`conftest.py`](conftest.py) | Forces `LLM_PROVIDER=mock`; `graph` and `ask(question)` fixtures. |
| [`test_chaos.py`](test_chaos.py) | Doctrine-driven chaos tests (model down, retrieval down, jailbreak in a chunk). (3) |
| [`test_policy_qa.py`](test_policy_qa.py) | Cited first-try answer, one rewrite-and-retry on weak retrieval, insufficient evidence after the retry budget, injection sanitising, groundedness failures, token-budget packing, BM25 ranking and a pluggable embedding retriever. (11) |

Numbers in brackets are test counts from `pytest --collect-only` (14 in total).

## Run

```bash
pytest projects/01-policy-qa-rag                      # from the repo root
pytest projects/01-policy-qa-rag/tests/test_chaos.py -v
```

Tests run offline against the deterministic mock model; no API keys or network needed.

## Chaos scenarios (from `doctrine.yaml`)

`test_chaos.py` is parametrized from the card's `chaos:` list, so adding a scenario to the card
adds a test. Each fault must make the named node take the declared exit, and the invariant is
checked by `CHAOS_CHECKS` in [`policy_qa/eval_suite.py`](../policy_qa/eval_suite.py).

| Fault | Node | Exit | Invariant |
|---|---|---|---|
| `model` | `generate_answer` | degrade | still answered with a verbatim, cited sentence (HR-PTO-2) |
| `retrieval` | `retrieve` | degrade | insufficient_evidence citing search outage; no answer generated from model memory |
| `jailbreak` | `retrieve` | degrade | poisoned chunk sanitized and flagged; answer grounded, no admin-mode text |
