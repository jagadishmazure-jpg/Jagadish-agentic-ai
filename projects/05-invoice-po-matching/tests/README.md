# `05-invoice-po-matching/tests/`: tests

Pytest suite for this project: behaviour of the graph and its guards, plus chaos tests driven
by the doctrine card. Shared fixtures such as `kill_model`, `kill_retrieval`, `kill_sor` and
`jailbreak`, and per-test fault isolation, come from the repo-root
[`conftest.py`](../../../conftest.py).

| File | What it does |
|---|---|
| [`conftest.py`](conftest.py) | `erp` (seeded mock ERP) and `graph` fixtures. |
| [`test_chaos.py`](test_chaos.py) | Doctrine-driven chaos tests. (3) |
| [`test_invoice_match.py`](test_invoice_match.py) | Clean approval and posting, typed variance exceptions with note, PO not found / closed, duplicate never paid twice, extraction retry with feedback, extraction budget, RetryPolicy on transient ERP errors, persistent outage propagates, price tolerance, note guard. (12) |

Numbers in brackets are test counts from `pytest --collect-only` (15 in total).

## Run

```bash
pytest projects/05-invoice-po-matching                      # from the repo root
pytest projects/05-invoice-po-matching/tests/test_chaos.py -v
```

Tests run offline against the deterministic mock model; no API keys or network needed.

## Chaos scenarios (from `doctrine.yaml`)

`test_chaos.py` is parametrized from the card's `chaos:` list, so adding a scenario to the card
adds a test. Each fault must make the named node take the declared exit, and the invariant is
checked by `CHAOS_CHECKS` in [`invoice_match/eval_suite.py`](../invoice_match/eval_suite.py).

| Fault | Node | Exit | Invariant |
|---|---|---|---|
| `model` | `extract` | degrade | clean invoice still approved via template parser; posted exactly once |
| `sor` | `fetch_erp` | retry | ERP outage retried then parked for redelivery; nothing posted, not misfiled as exception |
| `jailbreak` | `extract` | escalate | invoice with injected instruction goes to AP exceptions; nothing posted |
