# `11-customer-care-e2e/tests/`: tests

Pytest suite for this project: behaviour of the graph and its guards, plus chaos tests driven
by the doctrine card. Shared fixtures such as `kill_model`, `kill_retrieval`, `kill_sor` and
`jailbreak`, and per-test fault isolation, come from the repo-root
[`conftest.py`](../../../conftest.py).

| File | What it does |
|---|---|
| [`conftest.py`](conftest.py) | Forces `LLM_PROVIDER=mock` for every test in the folder. `systems`, `graph` and `ask(graph, message, customer, email, tenant)` fixtures. |
| [`test_bff.py`](test_bff.py) | BFF: identity from the token, channel claim and tenant checks, per tenant/channel rate limit, SSE event stream, HITL via the console endpoint and SLA sweep. (5) |
| [`test_care_graph.py`](test_care_graph.py) | All lanes and a single payment, policy as of the purchase date, ACL trimming of fraud playbook and billing-only cases, tenant isolation, fraud pre-route, confidence gate, large-refund HITL (agent cannot approve), SLA timeout, payments down then one redelivery, critic repair then escalate, planner budget and guard. (14) |
| [`test_chaos.py`](test_chaos.py) | Doctrine-driven chaos tests. (5) |
| [`test_http_topology.py`](test_http_topology.py) | The docker-compose topology without Docker: the three MCP servers run as streamable-HTTP apps in uvicorn threads and the graph reaches them through `CARE_MCP_URLS`. (1) |

Numbers in brackets are test counts from `pytest --collect-only` (25 in total).

## Run

```bash
pytest projects/11-customer-care-e2e                      # from the repo root
pytest projects/11-customer-care-e2e/tests/test_chaos.py -v
```

Tests run offline against the deterministic mock model; no API keys or network needed.

## Chaos scenarios (from `doctrine.yaml`)

`test_chaos.py` is parametrized from the card's `chaos:` list, so adding a scenario to the card
adds a test. Each fault must make the named node take the declared exit, and the invariant is
checked by `CHAOS_CHECKS` in [`care_e2e/eval_suite.py`](../care_e2e/eval_suite.py).

| Fault | Node | Exit | Invariant |
|---|---|---|---|
| `model` | `classify` | degrade | keyword classifier + template drafts; same $48.99 refund paid exactly once |
| `retrieval` | `policy` | degrade | no auto refund; paused for specialist approval; nothing paid |
| `sor:oms` | `order` | escalate | case opened with honest reply; nothing paid or invented |
| `sor:payments` | `finalize` | degrade | refund command queued in the outbox; reply gives a reference and never says issued |
| `jailbreak` | `history` | escalate | injected CRM case text neutralised; refund paused for a human; nothing paid |
