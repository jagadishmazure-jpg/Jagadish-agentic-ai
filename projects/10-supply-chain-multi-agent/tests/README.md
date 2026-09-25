# `10-supply-chain-multi-agent/tests/`: tests

Pytest suite for this project: behaviour of the graph and its guards, plus chaos tests driven
by the doctrine card. Shared fixtures such as `kill_model`, `kill_retrieval`, `kill_sor` and
`jailbreak`, and per-test fault isolation, come from the repo-root
[`conftest.py`](../../../conftest.py).

| File | What it does |
|---|---|
| [`conftest.py`](conftest.py) | `services`, `graph` and `start(sku)` fixtures (fresh thread per run). |
| [`test_chaos.py`](test_chaos.py) | Doctrine-driven chaos tests. (4) |
| [`test_sor.py`](test_sor.py) | Per-agent MCP identities: only the orchestrator can release or cancel, draft state transitions, semantic model serves only the certified measure. (3) |
| [`test_supply_chain_graph.py`](test_supply_chain_graph.py) | Routing order, parallel fan-out with a single join, no-reorder path, fallback supplier, reviewer loop and give-up, every number cites its producing agent, HITL approve / reject, idempotent submit after crash, iteration and cost guards, supervisor guard overrides, least-privilege tool scopes. (16) |

Numbers in brackets are test counts from `pytest --collect-only` (23 in total).

## Run

```bash
pytest projects/10-supply-chain-multi-agent                      # from the repo root
pytest projects/10-supply-chain-multi-agent/tests/test_chaos.py -v
```

Tests run offline against the deterministic mock model; no API keys or network needed.

## Chaos scenarios (from `doctrine.yaml`)

`test_chaos.py` is parametrized from the card's `chaos:` list, so adding a scenario to the card
adds a test. Each fault must make the named node take the declared exit, and the invariant is
checked by `CHAOS_CHECKS` in [`supply_chain/eval_suite.py`](../supply_chain/eval_suite.py).

| Fault | Node | Exit | Invariant |
|---|---|---|---|
| `model` | `supervisor` | degrade | deterministic routing + sourcing; same Acme PO released exactly once after approval |
| `sor:erp` | `inventory_agent` | retry | ERP down -> run deferred; no draft created, nothing released |
| `sor:erp.submit_purchase_order` | `submit_po` | compensate | release fails after approval -> draft cancelled, nothing released, buyer notified |
| `jailbreak` | `supplier_agent` | degrade | injected quote text neutralised before any agent/reviewer sees it; PO still reviewed and approved |
