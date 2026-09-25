# `04-sales-meeting-prep/tests/`: tests

Pytest suite for this project: behaviour of the graph and its guards, plus chaos tests driven
by the doctrine card. Shared fixtures such as `kill_model`, `kill_retrieval`, `kill_sor` and
`jailbreak`, and per-test fault isolation, come from the repo-root
[`conftest.py`](../../../conftest.py).

| File | What it does |
|---|---|
| [`conftest.py`](conftest.py) | `prep` fixture that runs the graph against seeded sources. |
| [`test_chaos.py`](test_chaos.py) | Doctrine-driven chaos tests. (4) |
| [`test_meeting_prep.py`](test_meeting_prep.py) | Complete cited brief, branches run in parallel, single fan-in, partial failure produces a brief with a gap, transient retry, quorum rule, uncited bullets dropped, requested subset of sources. (9) |

Numbers in brackets are test counts from `pytest --collect-only` (13 in total).

## Run

```bash
pytest projects/04-sales-meeting-prep                      # from the repo root
pytest projects/04-sales-meeting-prep/tests/test_chaos.py -v
```

Tests run offline against the deterministic mock model; no API keys or network needed.

## Chaos scenarios (from `doctrine.yaml`)

`test_chaos.py` is parametrized from the card's `chaos:` list, so adding a scenario to the card
adds a test. Each fault must make the named node take the declared exit, and the invariant is
checked by `CHAOS_CHECKS` in [`meeting_prep/eval_suite.py`](../meeting_prep/eval_suite.py).

| Fault | Node | Exit | Invariant |
|---|---|---|---|
| `model` | `synthesize` | degrade | brief still complete with rule-based cited bullets |
| `sor:crm` | `research` | degrade | CRM outage -> partial brief listing crm + deals gaps, verify manually |
| `sor` | `research` | degrade | all systems of record down -> insufficient_data banner, news only, nothing invented |
| `jailbreak` | `research` | degrade | injected CRM note neutralised; no admin text in the brief |
