# `02-ticket-triage/tests/`: tests

Pytest suite for this project: behaviour of the graph and its guards, plus chaos tests driven
by the doctrine card. Shared fixtures such as `kill_model`, `kill_retrieval`, `kill_sor` and
`jailbreak`, and per-test fault isolation, come from the repo-root
[`conftest.py`](../../../conftest.py).

| File | What it does |
|---|---|
| [`conftest.py`](conftest.py) | Forces `LLM_PROVIDER=mock`; `triage(body, ...)` fixture. |
| [`test_chaos.py`](test_chaos.py) | Doctrine-driven chaos tests. (3) |
| [`test_ticket_triage.py`](test_ticket_triage.py) | Routing to intent queues, critical urgency paging with a 1h SLA, mid-confidence clarification, low-confidence human review, PII redaction before any LLM call, Luhn check, one repair then escalate. (12) |

Numbers in brackets are test counts from `pytest --collect-only` (15 in total).

## Run

```bash
pytest projects/02-ticket-triage                      # from the repo root
pytest projects/02-ticket-triage/tests/test_chaos.py -v
```

Tests run offline against the deterministic mock model; no API keys or network needed.

## Chaos scenarios (from `doctrine.yaml`)

`test_chaos.py` is parametrized from the card's `chaos:` list, so adding a scenario to the card
adds a test. Each fault must make the named node take the declared exit, and the invariant is
checked by `CHAOS_CHECKS` in [`ticket_triage/eval_suite.py`](../ticket_triage/eval_suite.py).

| Fault | Node | Exit | Invariant |
|---|---|---|---|
| `model` | `classify` | degrade | routed to the human queue with 'classifier unavailable', no guessed route |
| `sor` | `billing_queue` | degrade | route kept, ticket queued in outbox with idempotency key triage:<id> |
| `jailbreak` | `redact_pii` | escalate | injected ticket goes to human review, not the requested queue |
