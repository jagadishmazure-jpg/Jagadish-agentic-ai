# `09-collections-agent/tests/`: tests

Pytest suite for this project: behaviour of the graph and its guards, plus chaos tests driven
by the doctrine card. Shared fixtures such as `kill_model`, `kill_retrieval`, `kill_sor` and
`jailbreak`, and per-test fault isolation, come from the repo-root
[`conftest.py`](../../../conftest.py).

| File | What it does |
|---|---|
| [`conftest.py`](conftest.py) | Forces `LLM_PROVIDER=mock` for every test in the folder. |
| [`test_chaos.py`](test_chaos.py) | Doctrine-driven chaos tests. (4) |
| [`test_collections.py`](test_collections.py) | Least-privilege scopes and audited denials, human approval before write identities act, rejection and separation of duties, policy branches never reach writers, contact-hours re-check at send time, plan clamping and message guard, audit hash chain tamper detection and PII masking, idempotent plan write, 7-day frequency cap. (12) |

Numbers in brackets are test counts from `pytest --collect-only` (16 in total).

## Run

```bash
pytest projects/09-collections-agent                      # from the repo root
pytest projects/09-collections-agent/tests/test_chaos.py -v
```

Tests run offline against the deterministic mock model; no API keys or network needed.

## Chaos scenarios (from `doctrine.yaml`)

`test_chaos.py` is parametrized from the card's `chaos:` list, so adding a scenario to the card
adds a test. Each fault must make the named node take the declared exit, and the invariant is
checked by `CHAOS_CHECKS` in [`collections_agent/eval_suite.py`](../collections_agent/eval_suite.py).

| Fault | Node | Exit | Invariant |
|---|---|---|---|
| `model` | `propose_plan` | degrade | policy-default plan + compliant template; still human-approved before sending |
| `sor` | `load_account` | retry | CRM down -> deferred to next run; nothing written or sent |
| `sor:payments.create_payment_plan` | `execute_plan` | degrade | ledger down after approval -> plan write queued, no message sent |
| `jailbreak` | `load_account` | degrade | injected account text neutralised; plan within policy; no injected text in outbound message |
