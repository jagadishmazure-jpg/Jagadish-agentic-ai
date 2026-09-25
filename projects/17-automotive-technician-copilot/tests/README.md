# `17-automotive-technician-copilot/tests/`: tests

Pytest suite for this project: behaviour of the graph and its guards, plus chaos tests driven
by the doctrine card. Shared fixtures such as `kill_model`, `kill_retrieval`, `kill_sor` and
`jailbreak`, and per-test fault isolation, come from the repo-root
[`conftest.py`](../../../conftest.py).

| File | What it does |
|---|---|
| [`conftest.py`](conftest.py) | Forces `LLM_PROVIDER=mock` for every test in the folder. |
| [`test_chaos.py`](test_chaos.py) | Doctrine-driven chaos tests. (5) |
| [`test_tech_copilot.py`](test_tech_copilot.py) | Current TSB wins over an unretired predecessor, as-of dates before supersession, wrong-version safety, build-date applicability, `current_only` needs a valid successor, diagram harness revision, part supersession in ATP, warranty always interrupts when covered, non-admin cannot approve, idempotent attributed claim, customer-pay path. (13) |

Numbers in brackets are test counts from `pytest --collect-only` (18 in total).

## Run

```bash
pytest projects/17-automotive-technician-copilot                      # from the repo root
pytest projects/17-automotive-technician-copilot/tests/test_chaos.py -v
```

Tests run offline against the deterministic mock model; no API keys or network needed.

## Chaos scenarios (from `doctrine.yaml`)

`test_chaos.py` is parametrized from the card's `chaos:` list, so adding a scenario to the card
adds a test. Each fault must make the named node take the declared exit, and the invariant is
checked by `CHAOS_CHECKS` in [`tech_copilot/eval_suite.py`](../tech_copilot/eval_suite.py).

| Fault | Node | Exit | Invariant |
|---|---|---|---|
| `model` | `procedure` | degrade | verbatim current bulletin (32 Nm), never the superseded spec |
| `retrieval` | `tsb` | degrade | no specs, no bulletin citations, no claim |
| `sor:parts` | `parts` | degrade | ATP unknown; guidance unaffected |
| `sor:warranty` | `warranty` | degrade | coverage unknown; no claim |
| `jailbreak` | `intake` | degrade | injected concern text neutralised; current bulletin still found |
