# `03-refund-agent/tests/`: tests

Pytest suite for this project: behaviour of the graph and its guards, plus chaos tests driven
by the doctrine card. Shared fixtures such as `kill_model`, `kill_retrieval`, `kill_sor` and
`jailbreak`, and per-test fault isolation, come from the repo-root
[`conftest.py`](../../../conftest.py).

| File | What it does |
|---|---|
| [`conftest.py`](conftest.py) | `services`, `graph` (explicit `MockChatModel`) and `run` fixtures; `run` starts a request on a fresh thread and returns `(result, config)` for resuming. |
| [`test_chaos.py`](test_chaos.py) | Doctrine-driven chaos tests (payments, OMS, CRM, model, retrieval outages and a jailbreak). (7) |
| [`test_refund_graph.py`](test_refund_graph.py) | Auto path, interrupt then approve / reject, identity failure, ineligible order with citation, fraud routing before money moves, idempotent replay after a crash, reply guard against leaked internals. (13) |

Numbers in brackets are test counts from `pytest --collect-only` (20 in total).

## Run

```bash
pytest projects/03-refund-agent                      # from the repo root
pytest projects/03-refund-agent/tests/test_chaos.py -v
```

Tests run offline against the deterministic mock model; no API keys or network needed.

## Chaos scenarios (from `doctrine.yaml`)

`test_chaos.py` is parametrized from the card's `chaos:` list, so adding a scenario to the card
adds a test. Each fault must make the named node take the declared exit, and the invariant is
checked by `CHAOS_CHECKS` in [`refund_agent/eval_suite.py`](../refund_agent/eval_suite.py).

| Fault | Node | Exit | Invariant |
|---|---|---|---|
| `model` | `classify_intent` | degrade | same outcome via keyword classifier + template reply; exactly one refund |
| `retrieval` | `check_refund_policy` | degrade | no auto refund; paused for human approval with cached policy citations |
| `sor:oms` | `verify_identity` | escalate | escalated; no money moved; nothing invented |
| `sor:payments` | `issue_refund` | degrade | refund queued with idempotency key; reply says not yet sent |
| `sor:crm.add_case_note` | `issue_refund` | degrade | worker replay deduped; money moved exactly once; CRM note queued |
| `sor:crm.add_case_note*1` | `issue_refund` | retry | transient CRM failure recovered by checkpoint replay; one refund |
| `jailbreak` | `check_refund_policy` | escalate | injected instructions never auto-pay; human approval required |
