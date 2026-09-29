# `21-multi-agent-orchestration-patterns/tests/`: tests

Pytest suite for this project: each pattern's structure and failure behaviour, the shared
harness, the arena graph, doctrine-driven chaos tests and the README-drift test for the
comparison table. Shared fixtures such as `kill_model` and per-test fault isolation come from
the repo-root [`conftest.py`](../../../conftest.py).

| File | What it does |
|---|---|
| [`conftest.py`](conftest.py) | Forces the mock model; `run` (one pattern graph) and `arena` (arena graph, fresh systems and thread) fixtures. |
| [`test_arena.py`](test_arena.py) | Arena nodes cover every pattern, HITL pause and resume for a referral, safety stops also reach the human gate, memo filed once by the orchestrator, workers cannot file, unknown loan rejected, as-of policy editions, ACL on committee minutes, decision rule matches the golden expectations. (9) |
| [`test_chaos.py`](test_chaos.py) | Doctrine-driven chaos tests (model down, loan system down, retrieval down, jailbreak). (4) |
| [`test_comparison.py`](test_comparison.py) | README comparison block and `evals/comparison.json` match a fresh run; the runner is deterministic; no fault cell is unsafe; no policy violations. (5) |
| [`test_harness.py`](test_harness.py) | Turn, token and LLM-call budgets; ping-pong detector; route validation; bad-handoff fault fires once; critical-path clock; one OTel span per agent turn; model down takes deterministic paths in five patterns. (9) |
| [`test_patterns.py`](test_patterns.py) | Every pattern resolves a clean case; per-pattern structure (fixed order, parallel starts, supervisor revision and route rejection, unparseable-output fallback, team leads and parallel teams, swarm handoffs, re-ask and ping-pong, debate and transcript cost, max rounds, magentic ledgers, replanning and stall stop, blackboard firing and fallback); worker down is a safe stop in six patterns. (28) |

Numbers in brackets are test counts from `pytest --collect-only` (55 in total).

## Run

```bash
pytest projects/21-multi-agent-orchestration-patterns                      # from the repo root
pytest projects/21-multi-agent-orchestration-patterns/tests/test_chaos.py -v
```

Tests run offline against the deterministic mock model; no API keys or network needed.

## Chaos scenarios (from `doctrine.yaml`)

| Fault | Node | Exit | Invariant |
|---|---|---|---|
| `model` | `supervisor` | degrade | every worker and the router take their deterministic path; zero LLM calls; correct decision filed once |
| `sor:loan_system` | `swarm` | escalate | researcher cannot read the file -> swarm refers the case; nothing filed |
| `retrieval` | `magentic` | escalate | policy agent fails; replan finds no capable agent for rules -> referral; nothing filed |
| `jailbreak` | `group_chat` | degrade | injected borrower note neutralised by the gateway; decision unchanged; no injected text in memo or trace |
