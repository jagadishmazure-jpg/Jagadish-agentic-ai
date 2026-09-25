# `12-agent-control-plane/tests/`: tests

Pytest suite for this project: behaviour of the graph and its guards, plus chaos tests driven
by the doctrine card. Shared fixtures such as `kill_model`, `kill_retrieval`, `kill_sor` and
`jailbreak`, and per-test fault isolation, come from the repo-root
[`conftest.py`](../../../conftest.py).

| File | What it does |
|---|---|
| [`conftest.py`](conftest.py) | Forces `LLM_PROVIDER=mock` for every test in the folder. `net` (the built network) and `ask(text, tenant, thread)` fixtures. |
| [`test_api.py`](test_api.py) | Registry admin API, register-then-gate flow, mounted A2A endpoints. (3) |
| [`test_chaos.py`](test_chaos.py) | Doctrine-driven chaos tests. (4) |
| [`test_journey.py`](test_journey.py) | Promise, shortfall drafts a rounded PO once, one trace across all A2A calls, tenant propagation, credit hold never promises, killed peer skipped, regex parse. (7) |
| [`test_plane.py`](test_plane.py) | Card at the well-known path, allowed call audited, unregistered / missing caller rejected, schema rejection, per-tenant policy, read-but-not-write for the marketing agent, allowed-callers and entitlement checks, kill switch and revive, budget exhaustion, promotion gate by side-effect class, unpromoted callee rejected. (15) |

Numbers in brackets are test counts from `pytest --collect-only` (29 in total).

## Run

```bash
pytest projects/12-agent-control-plane                      # from the repo root
pytest projects/12-agent-control-plane/tests/test_chaos.py -v
```

Tests run offline against the deterministic mock model; no API keys or network needed.

## Chaos scenarios (from `doctrine.yaml`)

`test_chaos.py` is parametrized from the card's `chaos:` list, so adding a scenario to the card
adds a test. Each fault must make the named node take the declared exit, and the invariant is
checked by `CHAOS_CHECKS` in [`control_plane/eval_suite.py`](../control_plane/eval_suite.py).

| Fault | Node | Exit | Invariant |
|---|---|---|---|
| `model` | `intake` | degrade | regex intake + template reply; same promise with ATP 360 |
| `a2a:sap-agent` | `sap` | degrade | stock unavailable -> cannot confirm; never says YES |
| `sor:crm` | `crm` | degrade | crm-agent's system down -> no customer data -> cannot confirm; no PO drafted |
| `jailbreak` | `crm` | degrade | instruction planted in CRM notes neutralised by crm-agent's sanitizer; promise still computed from data |
