# `15-banking-credit-memo/tests/`: tests

Pytest suite for this project: behaviour of the graph and its guards, plus chaos tests driven
by the doctrine card. Shared fixtures such as `kill_model`, `kill_retrieval`, `kill_sor` and
`jailbreak`, and per-test fault isolation, come from the repo-root
[`conftest.py`](../../../conftest.py).

| File | What it does |
|---|---|
| [`conftest.py`](conftest.py) | Forces `LLM_PROVIDER=mock` for every test in the folder. |
| [`test_chaos.py`](test_chaos.py) | Doctrine-driven chaos tests. (5) |
| [`test_credit_memo.py`](test_credit_memo.py) | Semantic layer rejects anything but governed measures, dry-run returns a plan without values, the graph dry-runs before executing, ownership changes over time, PD score from the model tool, memo cites governed sources, critic replaces invented numbers, dual control in graph and system, idempotent booking, fallback model cannot skip KYC. (10) |

Numbers in brackets are test counts from `pytest --collect-only` (15 in total).

## Run

```bash
pytest projects/15-banking-credit-memo                      # from the repo root
pytest projects/15-banking-credit-memo/tests/test_chaos.py -v
```

Tests run offline against the deterministic mock model; no API keys or network needed.

## Chaos scenarios (from `doctrine.yaml`)

`test_chaos.py` is parametrized from the card's `chaos:` list, so adding a scenario to the card
adds a test. Each fault must make the named node take the declared exit, and the invariant is
checked by `CHAOS_CHECKS` in [`credit_memo/eval_suite.py`](../credit_memo/eval_suite.py).

| Fault | Node | Exit | Invariant |
|---|---|---|---|
| `model` | `planner` | degrade | default plan still runs KYC; template memo; booked only with dual control |
| `retrieval` | `policy` | degrade | no limits policy -> refer; nothing booked |
| `sor:semantic` | `financials` | degrade | no governed financials -> refer; nothing booked |
| `sor:kyc` | `kyc` | escalate | screening outage stops the application; no memo |
| `jailbreak` | `memo` | escalate | injected RM notes neutralised and flagged; not in the memo; dual control unchanged |
