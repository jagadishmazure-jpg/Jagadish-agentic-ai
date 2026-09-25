# `16-telecom-outage-care/tests/`: tests

Pytest suite for this project: behaviour of the graph and its guards, plus chaos tests driven
by the doctrine card. Shared fixtures such as `kill_model`, `kill_retrieval`, `kill_sor` and
`jailbreak`, and per-test fault isolation, come from the repo-root
[`conftest.py`](../../../conftest.py).

| File | What it does |
|---|---|
| [`conftest.py`](conftest.py) | Forces `LLM_PROVIDER=mock` for every test in the folder. |
| [`test_chaos.py`](test_chaos.py) | Doctrine-driven chaos tests. (4) |
| [`test_outage_care.py`](test_outage_care.py) | Redundancy-aware blast radius, confirmed outage blocks offers and dispatch, stale feed disclosed, dispatch context pack, dispatch idempotent per day, bill citations follow the bill-period edition, NOC identity is read-only, NOC what-if. (8) |

Numbers in brackets are test counts from `pytest --collect-only` (12 in total).

## Run

```bash
pytest projects/16-telecom-outage-care                      # from the repo root
pytest projects/16-telecom-outage-care/tests/test_chaos.py -v
```

Tests run offline against the deterministic mock model; no API keys or network needed.

## Chaos scenarios (from `doctrine.yaml`)

`test_chaos.py` is parametrized from the card's `chaos:` list, so adding a scenario to the card
adds a test. Each fault must make the named node take the declared exit, and the invariant is
checked by `CHAOS_CHECKS` in [`outage_care/eval_suite.py`](../outage_care/eval_suite.py).

| Fault | Node | Exit | Invariant |
|---|---|---|---|
| `model` | `intake` | degrade | keyword intent + template; confirmed outage and ETA still stated |
| `sor:oss` | `status` | degrade | status unknown disclosed; no dispatch; no offers |
| `retrieval` | `bill_explain` | degrade | no tariff citations claimed; lines flagged for follow-up |
| `jailbreak` | `bill_explain` | degrade | injected bill text neutralised; never echoed |
