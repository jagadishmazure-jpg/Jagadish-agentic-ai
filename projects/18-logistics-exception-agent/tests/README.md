# `18-logistics-exception-agent/tests/`: tests

Pytest suite for this project: behaviour of the graph and its guards, plus chaos tests driven
by the doctrine card. Shared fixtures such as `kill_model`, `kill_retrieval`, `kill_sor` and
`jailbreak`, and per-test fault isolation, come from the repo-root
[`conftest.py`](../../../conftest.py).

| File | What it does |
|---|---|
| [`conftest.py`](conftest.py) | Forces `LLM_PROVIDER=mock` for every test in the folder. |
| [`test_chaos.py`](test_chaos.py) | Doctrine-driven chaos tests. (5) |
| [`test_exception_agent.py`](test_exception_agent.py) | Partitioning keeps shipment order, slip detection, crash and replay triggers once, malformed events dead-lettered and checkpointed, tracking refuses to interpolate, interpolating model guarded, notice only on high confidence and idempotent, low OCR confidence queues the claim, claim window by edition on ship date, capacity agent card, what-if and rejections, capacity refusal escalates while the notice continues. (14) |

Numbers in brackets are test counts from `pytest --collect-only` (19 in total).

## Run

```bash
pytest projects/18-logistics-exception-agent                      # from the repo root
pytest projects/18-logistics-exception-agent/tests/test_chaos.py -v
```

Tests run offline against the deterministic mock model; no API keys or network needed.

## Chaos scenarios (from `doctrine.yaml`)

`test_chaos.py` is parametrized from the card's `chaos:` list, so adding a scenario to the card
adds a test. Each fault must make the named node take the declared exit, and the invariant is
checked by `CHAOS_CHECKS` in [`exception_agent/eval_suite.py`](../exception_agent/eval_suite.py).

| Fault | Node | Exit | Invariant |
|---|---|---|---|
| `model` | `track` | degrade | template answer from the latest TMS event, cited |
| `sor:tms` | `intake` | degrade | honest unavailable answer; no event IDs or locations |
| `a2a:capacity-agent` | `whatif` | degrade | notice still drafted; no reroute options claimed |
| `retrieval` | `claim` | degrade | claim queued for review; no claim draft |
| `jailbreak` | `track` | degrade | injected scan remark neutralised; never echoed |
