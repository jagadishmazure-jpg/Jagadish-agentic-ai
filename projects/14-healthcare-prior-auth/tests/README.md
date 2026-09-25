# `14-healthcare-prior-auth/tests/`: tests

Pytest suite for this project: behaviour of the graph and its guards, plus chaos tests driven
by the doctrine card. Shared fixtures such as `kill_model`, `kill_retrieval`, `kill_sor` and
`jailbreak`, and per-test fault isolation, come from the repo-root
[`conftest.py`](../../../conftest.py).

| File | What it does |
|---|---|
| [`conftest.py`](conftest.py) | Forces `LLM_PROVIDER=mock` for every test in the folder. |
| [`test_chaos.py`](test_chaos.py) | Doctrine-driven chaos tests. (5) |
| [`test_prior_auth.py`](test_prior_auth.py) | PHI redaction in context and logs, ACL and plan-year retrieval, plan year changes the answer, draft-only until sign-off, portal rejects unsigned submission, eligibility failure is unknown, member channel refuses advice, kill switch scope, bad citation replaced by template. (12) |

Numbers in brackets are test counts from `pytest --collect-only` (17 in total).

## Run

```bash
pytest projects/14-healthcare-prior-auth                      # from the repo root
pytest projects/14-healthcare-prior-auth/tests/test_chaos.py -v
```

Tests run offline against the deterministic mock model; no API keys or network needed.

## Chaos scenarios (from `doctrine.yaml`)

`test_chaos.py` is parametrized from the card's `chaos:` list, so adding a scenario to the card
adds a test. Each fault must make the named node take the declared exit, and the invariant is
checked by `CHAOS_CHECKS` in [`prior_auth/eval_suite.py`](../prior_auth/eval_suite.py).

| Fault | Node | Exit | Invariant |
|---|---|---|---|
| `model` | `coverage_language` | degrade | template criteria wording; packet still clinician-signed and submitted |
| `retrieval` | `policy` | degrade | criteria unknown, no citations claimed |
| `sor:eligibility` | `eligibility` | degrade | eligibility unknown flagged on the packet, never assumed eligible |
| `sor:pa_portal` | `draft_packet` | degrade | nothing saved, nothing submitted |
| `jailbreak` | `intake` | escalate | injected note text removed from the packet and flagged for the clinician |
