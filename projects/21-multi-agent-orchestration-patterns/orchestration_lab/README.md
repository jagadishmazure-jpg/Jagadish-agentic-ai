# `orchestration_lab/`: one loan-exception task, eight orchestration patterns

The importable package for project 21. Shared worker agents (researcher, analyst, policy,
drafter, reviewer) resolve a mortgage underwriting exception; each module in
[`patterns/`](patterns/README.md) wires them into a different multi-agent topology as its own
LangGraph graph, inside a common harness. The arena graph runs any pattern behind one intake,
a human gate and a filing step, and the comparison runner scores all of them on the same
golden set.

| File | What it does |
|---|---|
| [`__init__.py`](__init__.py) | Package docstring. |
| [`agents.py`](agents.py) | The shared workers (`researcher`, `analyst`, `policy`, `drafter`, `reviewer`), each `fn(harness, state, meter) -> (ws_update, info)`. Research reads MCP systems of record through a scoped gateway; policy retrieves as-of the application date and validates the model's topic mapping; the drafter falls back to a deterministic memo; the reviewer is a code critic (decision, conditions, citations, numbers). With `peers=...` a worker also names its handoff target (swarm). |
| [`compare.py`](compare.py) | Comparison runner: every pattern over the golden `business` cases through `shared.evals.run_suite`, plus three injected faults per pattern; `render()` builds the README block, `main(write, check)` refreshes or verifies `README.md` and `evals/comparison.json`. |
| [`demo.py`](demo.py) | CLI behind `run.py`: all patterns on one loan, `--pattern` with the per-agent trace, `--fault`, `--hitl`, `--compare`, `--mermaid`. |
| [`domain.py`](domain.py) | Mock loan files, the policy rule registry (keyed by policy id), ratio math, compensating factors, the decision rule (`decide`), memo rendering, the no-fabricated-numbers check and the quality `score()`. |
| [`eval_suite.py`](eval_suite.py) | `run`, `run_case` (what `python -m evals` calls), `score_final`, `violations`, `chaos_scenario` and `CHAOS_CHECKS` (one pattern per chaos scenario). |
| [`graph.py`](graph.py) | `build_graph()`: the arena graph `intake -> <pattern> -> human_gate (interrupt) -> finalize (file memo, idempotent)`; `run_pattern()` runs one pattern graph directly; `PATTERNS` registry. |
| [`harness.py`](harness.py) | `Harness`: model calls with deterministic fallback, metered MCP/retrieval calls, `turn()` (one traced, metered agent turn with an OTel span), budgets (`Budgets`), ping-pong and repeated-review detection, route validation, `FaultPlan` (worker down, looping reviewer, bad handoff), `finish()` termination. Also the simulated latency constants. |
| [`knowledge.py`](knowledge.py) | Credit-policy corpus (DTI editions 2025 and 2026, LTV, credit score, compensating factors, delegated authority, missing documents, restricted committee minutes), the policy agent's principal and the context builder. |
| [`mock_llm.py`](mock_llm.py) | Deterministic responder per role (dispatched on `ROLE:` in the system prompt). Scripted imperfections: the drafter omits one condition from long first drafts; the advocate opens with a borrower-friendly proposal. |
| [`prompts.py`](prompts.py) | System prompts per role (workers, supervisor, team lead, moderator, advocate, risk officer, magentic manager plan / progress, handoff re-ask). |
| [`routing.py`](routing.py) | What each agent produces and needs, capability cards, `status()` (compact workspace view), `next_step()` (deterministic plan used by fallbacks and guards), `teams_todo()` for the hierarchy. |
| [`sor.py`](sor.py) | MCP servers `loan_system` and `credit_bureau` over mock `LoanSystems`, and three scoped gateways: researcher, analyst (read only) and the filer (orchestrator identity, `file_exception_memo` only). |
| [`state.py`](state.py) | `PatternState` with reducers (`merge_ws` for parallel workspace writes, additive counters, `latest_max` clock for critical-path latency) and `ArenaState`. |

## Design notes

- Workers never choose numbers: ratios and limits come from `domain.py` and the rule registry,
  and the reviewer rejects any memo that disagrees.
- The workspace (`ws`) is the only thing workers share; pattern bookkeeping lives in `control`,
  which only non-parallel nodes write.
- A failed worker turn records `ws.errors[agent]` instead of raising, so each pattern decides
  what a failure means (retry, replan, fallback source, or referral).

## Run

```bash
python projects/21-multi-agent-orchestration-patterns/run.py                    # demo (offline, mock LLM)
python projects/21-multi-agent-orchestration-patterns/run.py --mermaid projects/21-multi-agent-orchestration-patterns/graph.mmd
python projects/21-multi-agent-orchestration-patterns/run.py --compare --check  # README table fresh?
pytest projects/21-multi-agent-orchestration-patterns                           # tests
python -m evals --project 21                                                    # golden-set eval
CHAOS_FAULTS=model python projects/21-multi-agent-orchestration-patterns/run.py # every model deployment down
```

See the [project README](../README.md) for the comparison and the decision guide, and
[`DOCTRINE.md`](../DOCTRINE.md) for the five-exit table per node.
