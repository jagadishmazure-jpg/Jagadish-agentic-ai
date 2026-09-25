# `20-long-term-memory-agent/tests/`: tests

Pytest suite for this project: the memory store layer, the write policy and the agent across
sessions and users, plus chaos tests driven by the doctrine card. Shared fixtures such as
`kill_model`, `kill_retrieval` and `jailbreak`, and per-test fault isolation, come from the
repo-root [`conftest.py`](../../../conftest.py).

| File | What it does |
|---|---|
| [`conftest.py`](conftest.py) | Forces `LLM_PROVIDER=mock` for every test in the folder; `clock` (fake clock) and `agent` fixtures. |
| [`test_agent.py`](test_agent.py) | Long-term memory survives a new session, short-term memory is the thread checkpoint, `user_id` comes from config not the message, every Store read is scoped to the caller's namespace, right to be forgotten erases the Store and all threads, withdrawing consent stops writes and erases, a hallucinated citation is stripped, a poisoning attempt is flagged without storing the payload, a legacy poisoned record is quarantined at recall, the displayed reply has no citation markers. (10) |
| [`test_chaos.py`](test_chaos.py) | Doctrine-driven chaos tests. (3) |
| [`test_memory_store.py`](test_memory_store.py) | Relevant memory outranks irrelevant, a recent episode outranks an older one, TTL hides expired items and `sweep` deletes them, updates keep bounded history, forget leaves a content-free tombstone, namespaces are per user and require an identity. (6) |
| [`test_policy.py`](test_policy.py) | No consent means no write, instruction-like memories rejected and flagged, procedural memory limited to presentation keys, credentials and full identifiers never stored, identifiers redacted, low confidence skipped, inferred cannot override stated, a newer statement supersedes. (13) |

Numbers in brackets are test counts from `pytest --collect-only` (32 in total).

## Run

```bash
pytest projects/20-long-term-memory-agent                      # from the repo root
pytest projects/20-long-term-memory-agent/tests/test_chaos.py -v
```

Tests run offline against the deterministic mock model; no API keys or network needed.

## Chaos scenarios (from `doctrine.yaml`)

`test_chaos.py` is parametrized from the card's `chaos:` list, so adding a scenario to the card
adds a test. Each fault must make the named node take the declared exit, and the invariant is
checked by `CHAOS_CHECKS` in [`memory_agent/eval_suite.py`](../memory_agent/eval_suite.py).

| Fault | Node | Exit | Invariant |
|---|---|---|---|
| `model` | `respond` | degrade | holding reply with no memory citations; stored memories unchanged |
| `retrieval` | `recall` | degrade | memory store down → answer without memory and nothing recalled |
| `jailbreak` | `remember` | escalate | jailbreak text is never stored as a memory and the attempt is flagged |
