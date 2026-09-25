# `13-insurance-fnol-coverage/tests/`: tests

Pytest suite for this project: behaviour of the graph and its guards, plus chaos tests driven
by the doctrine card. Shared fixtures such as `kill_model`, `kill_retrieval`, `kill_sor` and
`jailbreak`, and per-test fault isolation, come from the repo-root
[`conftest.py`](../../../conftest.py).

| File | What it does |
|---|---|
| [`conftest.py`](conftest.py) | Forces `LLM_PROVIDER=mock` for every test in the folder. `systems` and `run(doc, review, llm)` fixtures. |
| [`test_chaos.py`](test_chaos.py) | Doctrine-driven chaos tests. (5) |
| [`test_fnol.py`](test_fnol.py) | OCR confidence pairs, low confidence queues without opening a claim, interrupt carries the proposal, edition decides seepage, retrieval scoped by edition and state, jurisdiction sublimits, fraud score from the tool and hidden from the claimant, leaky model guarded, authority limits, timeout never pays, idempotent payment, payable rules. (12) |

Numbers in brackets are test counts from `pytest --collect-only` (17 in total).

## Run

```bash
pytest projects/13-insurance-fnol-coverage                      # from the repo root
pytest projects/13-insurance-fnol-coverage/tests/test_chaos.py -v
```

Tests run offline against the deterministic mock model; no API keys or network needed.

## Chaos scenarios (from `doctrine.yaml`)

`test_chaos.py` is parametrized from the card's `chaos:` list, so adding a scenario to the card
adds a test. Each fault must make the named node take the declared exit, and the invariant is
checked by `CHAOS_CHECKS` in [`fnol/eval_suite.py`](../fnol/eval_suite.py).

| Fault | Node | Exit | Invariant |
|---|---|---|---|
| `model` | `intake` | degrade | keyword classifier still finds theft; adjuster-approved payment unchanged |
| `retrieval` | `coverage` | degrade | coverage unknown; nothing paid |
| `sor:fraud_ml` | `fraud` | degrade | no score; adjuster note says review manually |
| `sor:policy_admin` | `policy` | escalate | packet queued; nothing paid |
| `jailbreak` | `intake` | escalate | injected packet text queued for a human; nothing paid; not echoed |
