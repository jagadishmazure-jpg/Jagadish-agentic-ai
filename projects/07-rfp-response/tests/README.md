# `07-rfp-response/tests/`: tests

Pytest suite for this project: behaviour of the graph and its guards, plus chaos tests driven
by the doctrine card. Shared fixtures such as `kill_model`, `kill_retrieval`, `kill_sor` and
`jailbreak`, and per-test fault isolation, come from the repo-root
[`conftest.py`](../../../conftest.py).

| File | What it does |
|---|---|
| [`conftest.py`](conftest.py) | `result` fixture: the sample RFP run once through the graph. |
| [`test_chaos.py`](test_chaos.py) | Doctrine-driven chaos tests. (3) |
| [`test_library.py`](test_library.py) | Pricing entry is ACL-trimmed for presales; SLA edition follows the submission date. (2) |
| [`test_rfp_agent.py`](test_rfp_agent.py) | Every question answered once, sections via the worker subgraph, critic revision loop, retry budget then SME, no-KB questions go straight to SME, citations required and validated, compliance stripping, export-control legal review, planner fallback on bad LLM output. (12) |

Numbers in brackets are test counts from `pytest --collect-only` (17 in total).

## Run

```bash
pytest projects/07-rfp-response                      # from the repo root
pytest projects/07-rfp-response/tests/test_chaos.py -v
```

Tests run offline against the deterministic mock model; no API keys or network needed.

## Chaos scenarios (from `doctrine.yaml`)

`test_chaos.py` is parametrized from the card's `chaos:` list, so adding a scenario to the card
adds a test. Each fault must make the named node take the declared exit, and the invariant is
checked by `CHAOS_CHECKS` in [`rfp_agent/eval_suite.py`](../rfp_agent/eval_suite.py).

| Fault | Node | Exit | Invariant |
|---|---|---|---|
| `model` | `plan` | degrade | deterministic plan + verbatim cited drafts; same 8 answered, Q8 to SME |
| `retrieval` | `section_worker` | degrade | library down -> every question to SME, nothing drafted from model memory |
| `jailbreak` | `section_worker` | degrade | poisoned library entry neutralised; no admin text in the document |
