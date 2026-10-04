# 21 · Multi-Agent Orchestration Patterns: one loan exception, eight topologies, measured

> **Status:** ✅ Built. `pytest projects/21-multi-agent-orchestration-patterns` runs the offline tests, `python run.py` runs the demo and `python run.py --compare` regenerates the comparison below.

**Sections:** [1. Purpose](#1-purpose) · [2. Architecture](#2-architecture) · [3. How it works](#3-how-it-works) · [4. Key files](#4-key-files) · [5. Code excerpts](#5-code-excerpts) · [6. Configuration](#6-configuration) · [7. Commands](#7-commands) · [8. Real output](#8-real-output) · [9. Tests and eval gates](#9-tests-and-eval-gates) · [10. Guardrails](#10-guardrails) · [11. Security and governance](#11-security-and-governance) · [12. Observability](#12-observability) · [13. Failure modes](#13-failure-modes) · [14. Mapping to Azure services](#14-mapping-to-azure-services) · [15. Limitations](#15-limitations) · [16. Interview talking points](#16-interview-talking-points) · [17. Adopt this](#17-adopt-this)

## 1. Purpose

An underwriter raises an **exception ticket** on a mortgage application: "DTI is over the
limit, can we approve?" Resolving it takes four kinds of work that usually sit with different
people:

- **research**: pull the loan file, appraisal and credit summary from the loan origination
  system and credit bureau;
- **analysis**: compute DTI and LTV and find compensating factors (reserves, tenure, score);
- **policy check**: find the credit-policy edition in force on the *application date*;
- **drafting**: write a cited exception memo (approve, approve with conditions, decline, pend,
  or refer to credit committee) with every condition policy requires.

Everyone asks "should this be a supervisor, a swarm, a group chat...?" This project answers it
with numbers instead of opinions: **the same task, the same worker agents, the same tools, the
same golden set**, solved by eight orchestration patterns, each a LangGraph graph, all scored by
the same eval pipeline and pushed through the same injected faults.

> **In one line (from `doctrine.yaml`):** One realistic task (resolve a mortgage underwriting exception: research the loan file, analyse ratios, check the credit policy in force, draft a cited memo) solved by eight orchestration patterns as LangGraph graphs: sequential, concurrent fan-out/fan-in, supervisor, hierarchical teams, handoff swarm, moderated group chat/debate, magentic (task and progress ledgers) and blackboard. A common harness enforces budgets, loop and ping-pong detection, route validation, termination and tracing, and a comparison runner scores every pattern on the same golden set and under injected faults.

## 2. Architecture

### Patterns built

| Pattern | Module | How control flows | LangGraph mechanics |
|---|---|---|---|
| Sequential pipeline | [`patterns/sequential.py`](orchestration_lab/patterns/sequential.py) | researcher → analyst → policy → drafter → reviewer, once | static edges; a failure short-circuits to `finish` |
| Concurrent fan-out / fan-in | [`patterns/concurrent.py`](orchestration_lab/patterns/concurrent.py) | researcher ∥ policy ∥ analyst → join → drafter → reviewer | three edges from `START`, reducers on `ws`, `max` reducer on the clock |
| Supervisor (router) | [`patterns/supervisor.py`](orchestration_lab/patterns/supervisor.py) | an LLM supervisor picks the next worker after every turn; may fan out independent ones | `Send` fan-out, route validation, one retry, one revision |
| Hierarchical | [`patterns/hierarchical.py`](orchestration_lab/patterns/hierarchical.py) | top supervisor → evidence / policy / decision **team leads** → workers | each team is its own compiled subgraph; teams dispatched with `Send` |
| Handoff / swarm | [`patterns/swarm.py`](orchestration_lab/patterns/swarm.py) | peer-to-peer: each agent names the next peer in its own model call; no boss | `Command(goto=peer)` with declared `destinations` |
| Group chat / debate | [`patterns/group_chat.py`](orchestration_lab/patterns/group_chat.py) | moderator picks speakers over a shared transcript; advocate vs risk officer debate until consensus | transcript reducer; moderator ↔ speak loop with termination rules |
| Magentic-style | [`patterns/magentic.py`](orchestration_lab/patterns/magentic.py) | manager writes a **task ledger** (plan by capability), updates a **progress ledger** each round, detects stalls, **replans** | manager ↔ worker loop; ledgers in state; capability-based reassignment |
| Blackboard | [`patterns/blackboard.py`](orchestration_lab/patterns/blackboard.py) | no router model: a control component fires every agent whose preconditions are on the board | `Send` to all eligible sources each cycle |

All eight run inside one arena graph:

```mermaid
flowchart LR
    START([ticket]) --> IN["intake<br/>known loan + pattern?"]
    IN -- "pattern name" --> P{{"one of 8 pattern graphs<br/>(each its own StateGraph)"}}
    IN -- unknown --> FIN
    P --> HG["human_gate ⏸ interrupt()<br/>any referral: policy or safety stop"]
    HG --> FIN["finalize<br/>file memo (orchestrator identity, idempotent)"]
    FIN --> END([final report + per-agent trace])
    subgraph W["shared workers (orchestration_lab/agents.py)"]
        R["researcher 🤖<br/>loan_system · credit_bureau (MCP)"]
        A["analyst 🤖<br/>ratios · compensating factors"]
        PO["policy 🤖<br/>context builder, as-of + ACL"]
        D["drafter 🤖<br/>cited memo"]
        RV["reviewer (critic, code)<br/>decision · conditions · citations · numbers"]
    end
    P -.-> W
```

Compiled diagrams: [`graph.mmd`](graph.mmd) (arena) and [`graphs/<pattern>.mmd`](graphs/)
(each pattern, subgraphs expanded). Regenerate with `python run.py --mermaid graph.mmd`.

### Planes

<!-- output-md: python scripts/doc_tables.py 21 planes -->
| Plane | What this project depends on |
|---|---|
| Experience | underwriter exception ticket in; filed memo on the loan; credit officer approval step for referrals (interrupt payload with reason, citations and memo) |
| Agent | arena LangGraph graph (intake -> one of eight pattern graphs -> human_gate -> finalize); each pattern is its own graph over shared worker agents inside a common harness (budgets, loop detection, route validation, OTel spans per agent turn) |
| Knowledge | credit-policy corpus through the shared context builder (hybrid retrieval, ACL by principal, as-of the application date); restricted committee minutes trimmed before ranking |
| Data | loan origination system and credit bureau through MCP servers with one scoped gateway per identity; the memo is filed by the orchestrator identity only (idempotent, dry-run default) |
<!-- /output -->

## 3. How it works

Step by step, one line per graph node (the same nodes the promotion gate checks against the compiled graph):

<!-- output-md: python scripts/doc_tables.py 21 steps -->
1. **`intake`**: ticket loaded for a known loan and a registered pattern.
2. **`sequential`**: one pass researcher -> analyst -> policy -> drafter -> reviewer passes.
3. **`concurrent`**: researcher, policy and analyst fan out in one super-step; join; draft; review passes.
4. **`supervisor`**: validated routes until the reviewer passes the memo.
5. **`hierarchical`**: top supervisor runs evidence and policy teams in parallel, then the decision team; review passes.
6. **`swarm`**: peer handoffs until the reviewer hands off to END with a passed review.
7. **`group_chat`**: moderator-led chat reaches consensus, drafter writes, reviewer passes.
8. **`magentic`**: progress ledger reports the request satisfied after a passed review.
9. **`blackboard`**: control fires eligible sources until the review on the board passes.
10. **`human_gate`**: no referral, or a credit officer decides the referred file.
11. **`finalize`**: completed memo filed once (idempotency key per loan, pattern and decision).
<!-- /output -->

### The common harness

Every pattern gets the same controls from [`harness.py`](orchestration_lab/harness.py), so the
comparison measures topology, not who remembered to add a guard:

- **Budgets**: 30 agent turns, 40 LLM calls, 40k estimated tokens per run → `budget_exhausted:*`.
- **Loop control**: ping-pong detector (A-B-A-B-A-B), repeated-review-issues detector
  (no progress), magentic stall counter, revision caps.
- **Route validation**: every route, handoff or speaker a model proposes is checked against the
  agent registry and the target's prerequisites. A bad target is never executed.
- **Termination**: only a memo the reviewer passed is `completed`. Every other stop is a
  referral with an explicit `stop_reason`, never a guessed decision.
- **Tracing**: one OpenTelemetry span per agent turn (`agent <name>`, with pattern, run id, LLM
  calls, tokens, tool calls, simulated latency) under the LangGraph node spans from
  `shared/observability.py`; MCP tool spans nest under them.
- **HITL hook**: the arena's `human_gate` pauses any referral at `interrupt()` for a credit
  officer, whichever pattern produced it.
- **Fault plan** for the comparison: one worker down (1.5 s timeout), a reviewer that is never
  satisfied, and a bad handoff (the first model-chosen route names `funds_disbursement_agent`).

**LLM proposes, code disposes.** Ratios, limits and the decision rule live in
[`domain.py`](orchestration_lab/domain.py) and the rule registry keyed by policy id. Agents
retrieve, map evidence, phrase and route; the reviewer recomputes the decision from facts plus
the cited rules and rejects any memo whose decision, conditions, citations or numbers disagree.

### Which pattern when

| If the task looks like... | Use | Why (from the numbers above) |
|---|---|---|
| A fixed procedure, and a wrong answer is safely caught downstream | **Sequential** | Fewest moving parts and model calls; but no loop back, so any critic finding becomes a referral |
| Independent lookups that dominate latency | **Concurrent** | Same calls as sequential, shortest simulated latency; pays in duplicate tool reads, still no loop |
| A known process with dependencies, a need to retry, audit and budget in one place | **Supervisor** | Full quality, one place for guards; roughly one routing call per worker call |
| Many agents in clear sub-domains, where one router's context would blow up | **Hierarchical** | Keeps each router's view small; costs an extra routing layer (most calls after group chat) |
| Work where each step knows who should go next (conversational handoffs) | **Swarm** | Near-sequential cost with loops, because routing rides inside the worker's own call; needs handoff validation and ping-pong detection |
| A judgement call that benefits from opposing views | **Group chat / debate** | Only pattern where a biased proposal is argued down; shared transcript makes it the most expensive by far |
| Open-ended tasks, unreliable workers, unknown plans | **Magentic** | Only model-routed pattern that recovered from a dead worker (replanned onto a capable agent); pays two manager calls per step |
| Data-driven workflows where "who can act" follows from "what's known" | **Blackboard** | Cheapest full-quality pattern here and recovers from the dead analyst; only works when preconditions are crisp enough to code |

## 4. Key files

| Path | What it is |
|---|---|
| [`orchestration_lab/`](orchestration_lab/README.md) | The importable package (domain, workers, harness, eight pattern graphs, arena graph, comparison runner, eval suite, demo), with a file-by-file map. |
| [`orchestration_lab/patterns/`](orchestration_lab/patterns/README.md) | One module per orchestration pattern. |
| [`tests/`](tests/README.md) | Pytest suite, including chaos tests generated from `doctrine.yaml` and the README-drift test. |
| [`evals/`](evals/README.md) | Golden set, `scores.json` and `comparison.json`. |
| [`run.py`](run.py) | Demo entry point (adds the package and repo root to `sys.path`). |
| [`doctrine.yaml`](doctrine.yaml) | Machine-checked doctrine card: planes, systems of record, corpus and ACL, stop conditions, five-exit table, chaos scenarios, eval thresholds, KPIs. |
| [`DOCTRINE.md`](DOCTRINE.md) | Generated from the card and `evals/scores.json` by `python -m shared.doctrine render`; do not edit by hand. |
| [`graph.mmd`](graph.mmd), [`graphs/`](graphs/) | Mermaid diagrams of the compiled arena and pattern graphs. |

Shared platform code (context builder, tool gateway, MCP kit, resilience, evals, doctrine) lives in
[`shared/`](../../shared/README.md).

## 5. Code excerpts

The graph wiring, from `build_graph` in [`graph.py`](orchestration_lab/graph.py) (node functions are defined above it in the same file):

<!-- code: projects/21-multi-agent-orchestration-patterns/orchestration_lab/graph.py::build_graph|StateGraph( -->
```python
# build_graph() continued: wiring
g = StateGraph(ArenaState)

def intake(state: dict[str, Any]) -> dict[str, Any]:
    loan_id = state.get("loan_id", "")
    pattern = state.get("pattern") or DEFAULT_PATTERN
    if loan_id not in domain.LOANS or pattern not in PATTERNS:
        result = {
            "decision": "rejected",
            "conditions": [],
            "citations": [],
            "memo": "",
            "stop_reason": "unknown loan or pattern",
        }
        return {
            "pattern": pattern,
            "result": result,
            "exits": [exit_record("intake", "escalate", result["stop_reason"])],
        }
    return {"pattern": pattern, "ticket": domain.ticket(loan_id)["text"]}

def pattern_node(name: str):
    def node(state: dict[str, Any]) -> dict[str, Any]:
        h = Harness(name, systems=systems, llm=llm, budgets=budgets, faults=faults)
        out = PATTERNS[name].build(h).invoke(initial_state(domain.ticket(state["loan_id"])))
        return {"run": summarize(out), "result": out["result"], "exits": out.get("exits", [])}

    node.__name__ = name
    return node

def human_gate(state: dict[str, Any]) -> dict[str, Any]:
    result = state["result"]
    if not hitl or result["decision"] != "escalate":
        return {}
    answer = interrupt(
        {
            "loan_id": state["loan_id"],
            "pattern": state["pattern"],
            "reason": result["stop_reason"]
            if result["stop_reason"] != "completed"
            else "policy referral (credit committee / delegated authority)",
            "citations": result["citations"],
            "memo": result["memo"],
            "ask": "credit officer decision: approve | approve_with_conditions | decline "
            "| pend",
        }
    )
    return {
        "human": dict(answer),
        "exits": [exit_record("human_gate", "escalate", f"referred: {result['stop_reason']}")],
        "result": {**result, "referral_reason": result["stop_reason"]},
    }

def finalize(state: dict[str, Any]) -> dict[str, Any]:
    result = dict(state["result"])
    human = state.get("human") or {}
    filed = None
    exits: list[dict[str, str]] = []
    if human:
        result["decision"] = human.get("decision", result["decision"])
        result["decided_by"] = human.get("approver", "credit-officer")
        if result.get("memo"):
            result["memo"] += (
                f" Credit officer decision: {result['decision']} ({result['decided_by']})."
            )
    if result.get("memo") and result["stop_reason"] == "completed":
        key = f"memo:{state['loan_id']}:{state['pattern']}:{result['decision']}"
        try:
            filed = filer.call(
                "loan_system",
                "file_exception_memo",
                loan_id=state["loan_id"],
                decision=result["decision"],
                memo=result["memo"],
                idempotency_key=key,
                dry_run=False,
            )
        except SystemOfRecordUnavailableError as exc:
            exits.append(exit_record("finalize", "escalate", f"memo not filed: {exc}"))
    final = {
        "pattern": state["pattern"],
        "loan_id": state["loan_id"],
        **result,
        "human": human or None,
        "filed": filed,
        "metrics": {k: v for k, v in (state.get("run") or {}).items() if k != "trace"},
        "trace": (state.get("run") or {}).get("trace", []),
    }
    return {"final": final, "exits": exits}

g.add_node("intake", intake)
for name in PATTERNS:
    g.add_node(name, pattern_node(name))
    g.add_edge(name, "human_gate")
g.add_node("human_gate", human_gate)
g.add_node("finalize", finalize)
g.add_edge(START, "intake")
g.add_conditional_edges(
    "intake",
    lambda s: "finalize" if s.get("result") else s["pattern"],
    [*PATTERNS, "finalize"],
)
g.add_edge("human_gate", "finalize")
g.add_edge("finalize", END)
return g.compile(checkpointer=checkpointer if checkpointer is not None else InMemorySaver())
```
<!-- /code -->

How one golden case is run and scored, from `run_case` in [`eval_suite.py`](orchestration_lab/eval_suite.py):

<!-- code: projects/21-multi-agent-orchestration-patterns/orchestration_lab/eval_suite.py::run_case -->
```python
def run_case(case: dict[str, Any], pattern: str | None = None) -> CaseResult:
    r, s = run(case["input"], pattern)
    final = r.get("final") or {}
    success, grounded, checks = score_final(case, r)
    return CaseResult(
        case["id"],
        success,
        grounded,
        violations(final, s, bool(case["input"].get("human"))),
        detail=f"decision={final.get('decision')} stop={final.get('stop_reason')} "
        f"failed_checks={[k for k, v in checks.items() if not v]}",
    )
```
<!-- /code -->

## 6. Configuration

| Setting | Where | Effect |
|---|---|---|
| `LLM_PROVIDER` | environment | `mock` (default when nothing is set), `azure` or `openai` |
| `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_DEPLOYMENT` | environment | real Azure OpenAI model, keyless through `DefaultAzureCredential`; `AZURE_OPENAI_API_KEY` only if set |
| `AZURE_OPENAI_FALLBACK_DEPLOYMENT` | environment | second deployment behind the circuit breaker |
| `CHAOS_FAULTS` | environment | inject faults for a demo run; this project's scenarios: `model`, `sor:loan_system`, `retrieval`, `jailbreak` |
| `OTEL_CONSOLE=1` / `OTEL_EXPORTER_OTLP_ENDPOINT` | environment | print spans, or ship them to a collector |
| `doctrine.yaml` | this folder | thresholds, stop conditions, identities, KPIs, chaos scenarios |
| `evals/golden.jsonl` | this folder | golden cases the eval gate runs |

Eval thresholds the gate enforces:

<!-- output-md: python scripts/doc_tables.py 21 thresholds -->
| Metric | Threshold (doctrine.yaml) | Current (evals/scores.json) |
|---|---|---|
| `task_success` | `>=0.95` | 1.00 |
| `groundedness` | `>=0.95` | 1.00 |
| `policy_violation_rate` | `<=0` | 0.00 |
| `cost_per_task` | `<=0.003` | 0.00047 |
<!-- /output -->

## 7. Commands

From the repo root, after `uv sync --all-extras --group dev`:

```bash
python projects/21-multi-agent-orchestration-patterns/run.py                          # L-2105 through all 8 patterns + a trace
python projects/21-multi-agent-orchestration-patterns/run.py --pattern swarm --loan L-2111
python projects/21-multi-agent-orchestration-patterns/run.py --pattern magentic --loan L-2101 --fault analyst_down
python projects/21-multi-agent-orchestration-patterns/run.py --hitl                   # referral -> credit officer -> filed
python projects/21-multi-agent-orchestration-patterns/run.py --compare [--write|--check]
pytest projects/21-multi-agent-orchestration-patterns
python -m evals --project 21
```

With Azure OpenAI or OpenAI variables set, every role uses the real model through the same
prompts; the guards, critic, budgets and human gate stay the same, and `--compare` then measures
real-model behaviour (tokens from the estimator, latency still simulated).

### Gates for this project

```bash
pytest projects/21-multi-agent-orchestration-patterns   # unit + chaos tests, offline
python -m evals --project 21 --no-write   # golden set vs doctrine thresholds
python -m shared.doctrine validate   # promotion gate (all projects)
python scripts/render_docs.py --check   # this README's pasted output is current
```

## 8. Real output

`python projects/21-multi-agent-orchestration-patterns/run.py` against the mock model (pasted by `scripts/render_docs.py`; trace and span ids are masked):

<!-- output: python projects/21-multi-agent-orchestration-patterns/run.py -->
```text
=== L-2105 through every pattern
sequential    escalate                 review_failed                    turns= 5 llm= 4 tokens= 1076 sim=  5.8s
concurrent    escalate                 review_failed                    turns= 5 llm= 4 tokens= 1076 sim=  3.9s
supervisor    approve_with_conditions  completed                        turns=14 llm=12 tokens= 2484 sim= 10.7s
hierarchical  approve_with_conditions  completed                        turns=20 llm=18 tokens= 3229 sim= 11.4s
swarm         approve_with_conditions  completed                        turns= 7 llm= 5 tokens= 1661 sim=  7.9s
group_chat    approve_with_conditions  completed                        turns=23 llm=21 tokens= 7797 sim= 19.5s
magentic      approve_with_conditions  completed                        turns=16 llm=14 tokens= 3283 sim= 15.2s
blackboard    approve_with_conditions  completed                        turns= 7 llm= 5 tokens= 1415 sim=  6.8s

=== per-agent trace: supervisor
supervisor    approve_with_conditions  completed                        turns=14 llm=12 tokens= 2484 sim= 10.7s
  agent                     start s  sim ms  llm tokens tools  note
  supervisor                   0.00     644    1    148     0  route ['researcher', 'policy']
  researcher                   0.64    1142    1    151     3  facts gathered
  policy                       0.64    2076    1    477     0  as of 2026-03-16
  supervisor                   2.72     560    1    145     0  route ['analyst']
  analyst                      3.28     763    1    135     0  ratios by analyst
  supervisor                   4.04     560    1    148     0  route ['drafter']
  drafter                      4.60    1800    1    313     0  draft r1
  supervisor                   6.40     573    1    150     0  route ['reviewer']
  reviewer                     6.98      20    0      0     0  FAIL ['missing condition: employment_reverification']
  supervisor                   7.00     561    1    163     0  route ['drafter']
  drafter                      7.56    1968    1    339     0  draft r2
  supervisor                   9.53     573    1    164     0  route ['reviewer']
  reviewer                    10.10      20    0      0     0  PASS
  supervisor                  10.12     561    1    151     0  route ['FINISH']
  memo: Exception memo L-2105: APPROVE WITH CONDITIONS. DTI 47.0% [CP-DTI-2026]. LTV 86.0% [CP-LTV-2026]. Credit score 750 [CP-FICO-2026]. See [CP-COMP-2026]. See [CP-AUTH-2026]. Conditions: verify_reserves; employment_reverification; mortgage_insurance; senior_underwriter_signoff.
```
<!-- /output -->

### Results (generated by `python run.py --compare --write`)

The numbers below come from the runner, not from hand editing:
`tests/test_comparison.py` re-runs it and fails if this block or
[`evals/comparison.json`](evals/comparison.json) differ from a fresh run.

<!-- comparison:start -->
Business cases: 14 (every `business` case in `evals/golden.jsonl`), offline deterministic mock model. Tokens are estimates (characters / 4); latency is **simulated** from the harness latency model (critical path, parallel branches overlap), not a measurement.

| Pattern | Quality (task success) | Grounded | Policy viol. | LLM calls / case | Est. tokens / case | Tool calls / case | Agent turns / case | Sim. latency / case (s) | Failed cases |
|---|---|---|---|---|---|---|---|---|---|
| sequential | 0.79 | 0.79 | 0.00 | 4.0 | 1,030 | 3.0 | 5.0 | 5.3 | `l-2105`, `l-2111`, `l-2113` |
| concurrent | 0.79 | 0.79 | 0.00 | 4.0 | 1,030 | 6.0 | 5.0 | 3.5 | `l-2105`, `l-2111`, `l-2113` |
| supervisor | 1.00 | 1.00 | 0.00 | 9.6 | 1,915 | 3.0 | 10.9 | 7.7 | none |
| hierarchical | 1.00 | 1.00 | 0.00 | 15.6 | 2,695 | 3.0 | 16.9 | 8.5 | none |
| swarm | 1.00 | 1.00 | 0.00 | 4.2 | 1,289 | 3.0 | 5.4 | 5.8 | none |
| group_chat | 1.00 | 1.00 | 0.00 | 17.5 | 5,329 | 3.0 | 18.7 | 14.5 | none |
| magentic | 1.00 | 1.00 | 0.00 | 11.6 | 2,627 | 3.0 | 12.9 | 12.0 | none |
| blackboard | 1.00 | 1.00 | 0.00 | 4.2 | 1,103 | 3.0 | 5.4 | 4.7 | none |

Failure behaviour on `L-2101` (cell: outcome · agent turns · LLM calls before the run ended; *recovered* = correct decision completed, *safe stop* = referral with a reason and nothing filed, *UNSAFE* = wrong decision completed):

| Pattern | Analyst down | Looping reviewer | Bad handoff |
|---|---|---|---|
| sequential | safe stop: worker_failed:analyst · 2 turns · 1 calls | safe stop: review_failed · 5 turns · 4 calls | n/a (no model-chosen routes) |
| concurrent | safe stop: worker_failed:analyst · 3 turns · 2 calls | safe stop: review_failed · 5 turns · 4 calls | n/a (no model-chosen routes) |
| supervisor | safe stop: worker_failed:analyst · 7 turns · 5 calls | safe stop: review_failed_after_revision · 14 turns · 12 calls | recovered · 10 turns · 9 calls |
| hierarchical | safe stop: worker_failed:analyst · 8 turns · 7 calls | safe stop: review_failed_after_revision · 19 turns · 17 calls | recovered · 16 turns · 15 calls |
| swarm | safe stop: worker_failed:analyst · 2 turns · 1 calls | safe stop: ping_pong_detected · 8 turns · 6 calls | recovered · 6 turns · 5 calls |
| group_chat | safe stop: worker_failed:analyst · 4 turns · 3 calls | safe stop: no_progress · 22 turns · 20 calls | recovered · 19 turns · 18 calls |
| magentic | recovered · 16 turns · 14 calls | safe stop: stalled · 28 turns · 24 calls | recovered · 12 turns · 11 calls |
| blackboard | recovered · 6 turns · 4 calls | safe stop: no_progress · 7 turns · 5 calls | n/a (no model-chosen routes) |
<!-- comparison:end -->

**How to read this honestly.**
- Offline, the model is a deterministic mock ([`mock_llm.py`](orchestration_lab/mock_llm.py)).
  It has one scripted weakness: the drafter drops `employment_reverification` from a first
  draft with three or more conditions, and fixes it when a reviewer issue names it. That is what
  separates patterns with a feedback loop (1.00) from the one-pass ones: the pipeline and
  fan-out can only refer those three files. Against a real model the size of that gap is
  something to measure, not assume.
- Token counts are `len(text) / 4` estimates of the real prompts; latency is simulated
  (350 ms per call + 12 ms per output token, 150 ms per MCP call, 200 ms per retrieval, parallel
  branches overlap). Both are good for *relative* comparison between patterns only.
- The fault table uses one case (`L-2101`) so every cell is the same task under a different
  failure.

## 9. Tests and eval gates

Tests collected for this project:

<!-- output-md: python scripts/doc_tables.py 21 tests -->
| Test file | Tests |
|---|---|
| `test_arena.py` | 9 |
| `test_chaos.py` | 4 |
| `test_comparison.py` | 5 |
| `test_harness.py` | 9 |
| `test_patterns.py` | 28 |
| **total** | **55** |
<!-- /output -->

Eval gate for this project (`python -m evals --project 21 --no-write`):

<!-- output: python -m evals --project 21 --no-write -->
```text
project                            n   task_success   groundedness policy_violati tool_error_rat  cost_per_task  gate
---------------------------------------------------------------------------------------------------------------------
21-multi-agent-orchestration-patterns  24           1.00           1.00           0.00           0.00        0.00046  PASS

eval gate: 1/1 projects pass
```
<!-- /output -->

### Tests

- every pattern resolves a clean case; structure per pattern (fixed order, parallel starts,
  team leads and parallel teams, no router turns in a swarm, debate rounds and consensus,
  task/progress ledgers and replanning, blackboard parallel firing and capability fallback)
- harness: turn / token / LLM-call budgets, ping-pong, route validation, the critical-path
  clock, one OTel span per agent turn, model-down deterministic paths
- arena: HITL pause and resume, safety stops also go to the human, filing once by the
  orchestrator identity only, unknown loan rejection, as-of policy editions, ACL on committee
  minutes, decision rule matches the golden expectations
- chaos tests generated from `doctrine.yaml`
- the comparison block and `comparison.json` match a fresh deterministic run

## 10. Guardrails

Stop conditions (from `doctrine.yaml`; each one is enforced in code or by the gateway):

<!-- output-md: python scripts/doc_tables.py 21 stop -->
- harness budgets per run (30 agent turns, 40 LLM calls, 40k estimated tokens) -> budget_exhausted referral
- loop control per pattern - one revision (supervisor, hierarchical), ping-pong A-B-A-B-A-B (swarm), repeated review issues (group chat, blackboard), stall counter with at most one replan (magentic), 16 speaker rounds (group chat)
- every model-proposed route, handoff or speaker is validated against the registry and prerequisites; a bad target is rejected (fallback or one re-ask), never executed
- only a reviewer-passed memo counts as completed; every other stop is a referral to the human gate, never a guessed decision
- no agent can file; filing is the orchestrator identity in finalize, idempotent per loan, pattern and decision
<!-- /output -->

Tool identities and allow-lists (the `ToolGateway` refuses anything else):

<!-- output-md: python scripts/doc_tables.py 21 identities -->
| Tool identity | Allowed tools (gateway allow-list) |
|---|---|
| `mi-exception-researcher` | `loan_system.get_loan_file`, `loan_system.get_appraisal`, `credit_bureau.get_credit_summary` |
| `mi-exception-analyst` | `loan_system.get_loan_file`, `loan_system.get_appraisal`, `credit_bureau.get_credit_summary` |
| `mi-exception-filer` | `loan_system.file_exception_memo` |
<!-- /output -->

### Anti-patterns (each one tested)

- **Router without validation.** A supervisor that executes whatever the model names will one
  day route to `funds_disbursement_agent`. Every pattern here rejects unregistered targets
  (`test_supervisor_rejects_an_invalid_route`, `test_swarm_reasks_after_a_bad_handoff`).
- **Swarm without a loop breaker.** Two agents that disagree hand off forever. The ping-pong
  detector ends it (`test_swarm_has_no_router_turns_and_detects_ping_pong`).
- **Group chat as the default.** Everyone reads everything, so cost grows with the transcript
  (`test_group_chat_debate_shares_the_transcript` asserts the second draft costs more).
- **"The manager will figure it out" without stall detection.** A never-satisfied critic
  burns the budget; the stall counter plus one replan ends it (`test_magentic_stall_detection_ends_a_loop`).
- **Guessing on failure.** A pattern that "completes" with a missing worker would file a memo
  without analysis. Here a dead worker is recovered (magentic, blackboard) or referred with a
  reason (`test_worker_down_is_a_safe_stop`), and `test_no_pattern_completes_a_wrong_decision_under_faults`
  checks no cell is unsafe.
- **Parallel writes to a plain dict.** Fan-out branches need reducers (`merge_ws`, `max`
  clock), or LangGraph raises `InvalidUpdateError`.
- **Summing parallel latency.** The clock keeps the max of branches, so concurrency shows up as
  a shorter critical path (`test_clock_reports_critical_path_not_sum`).

## 11. Security and governance

The full card is in [`DOCTRINE.md`](DOCTRINE.md), generated from [`doctrine.yaml`](doctrine.yaml).

- **Systems of record behind MCP, one identity per role.** Researcher and analyst read through
  their own gateways; only the orchestrator identity (`mi-exception-filer`) can file a memo.
- **Knowledge plane.** Policy comes from the shared context builder, as-of the application date,
  with committee minutes ACL-trimmed before ranking.
- **Five exits per node** for all eleven arena nodes (each pattern is a node), with chaos
  scenarios on four different patterns.

```bash
python -m evals --project 21
pytest projects/21-multi-agent-orchestration-patterns/tests/test_chaos.py
```

### Systems of record

<!-- output-md: python scripts/doc_tables.py 21 sor -->
| System of record | Kind | Contract | Access |
|---|---|---|---|
| Loan origination system | mcp | `loan_system.get_loan_file, loan_system.get_appraisal (read); loan_system.file_exception_memo (write, idempotent)` | read_write |
| Credit bureau | mcp | `credit_bureau.get_credit_summary (read)` | read |
<!-- /output -->

### Knowledge corpora and ACL

<!-- output-md: python scripts/doc_tables.py 21 knowledge -->
| Corpus | Owner | ACL | Temporal validity | Sensitivity |
|---|---|---|---|---|
| credit-policy | credit-policy | underwriting group; committee minutes restricted to credit-committee | DTI rule has 2025 and 2026 editions; retrieval as-of the application date | internal |
<!-- /output -->

## 12. Observability

Every run emits OpenTelemetry spans through `shared/observability.py`: one for the graph, one per node, one per model call (tokens, estimated cost, deployment) and one per tool call (identity, tool, status). Spans stay in memory by default; `OTEL_CONSOLE=1` prints them and `OTEL_EXPORTER_OTLP_ENDPOINT` ships them. Eval runs write `evals/scores.json`, which `DOCTRINE.md` renders.

```bash
OTEL_CONSOLE=1 python projects/21-multi-agent-orchestration-patterns/run.py   # watch the spans for one demo run
```

KPIs this project is meant to be judged on:

<!-- output-md: python scripts/doc_tables.py 21 kpis -->
| KPI | Target | How it is measured |
|---|---|---|
| Exception memos accepted without rework | >= 90% of completed memos | senior underwriter QC outcome per filed memo |
| Wrong exception decisions filed | 0 | QC overturns where the filed decision contradicts the policy edition in force |
| Referral precision | >= 80% of referrals need a committee or officer decision | credit officer disposition of human_gate referrals |
| Cost per resolved exception | tracked per pattern; alert on +25% week over week | LLM calls and tokens per case from agent spans |
<!-- /output -->

## 13. Failure modes

Five exits per node (success, retry, compensate, degrade, escalate):

<!-- output-md: python scripts/doc_tables.py 21 playbook -->
| Node | Success | Retry | Compensate | Degrade | Escalate |
|---|---|---|---|---|---|
| `intake` | ticket loaded for a known loan and a registered pattern | n/a (local ticket read) | n/a | n/a | unknown loan or pattern -> rejected, nothing runs |
| `sequential` | one pass researcher -> analyst -> policy -> drafter -> reviewer passes | gateway backoff on SoR reads only | n/a (read-only until finalize) | model down -> each worker's deterministic path | any worker failure or a failed review (no loop back) -> referral |
| `concurrent` | researcher, policy and analyst fan out in one super-step; join; draft; review passes | gateway backoff on SoR reads only | n/a (read-only until finalize) | model down -> deterministic worker paths | a failed branch or failed review -> referral |
| `supervisor` | validated routes until the reviewer passes the memo | one retry per failed worker; one revision after a failed review | n/a (read-only until finalize) | invalid/unparseable route or model down -> deterministic plan | worker fails twice, second review failure or budget -> referral |
| `hierarchical` | top supervisor runs evidence and policy teams in parallel, then the decision team; review passes | one revision inside the decision team | n/a (read-only until finalize) | invalid top or team-lead route -> deterministic team plan | a failed member ends its team and the top supervisor refers the file |
| `swarm` | peer handoffs until the reviewer hands off to END with a passed review | an invalid handoff target gets one re-ask of the sending agent | n/a (read-only until finalize) | model down -> deterministic handoff choice | second bad handoff, ping-pong, worker down or budget -> referral |
| `group_chat` | moderator-led chat reaches consensus, drafter writes, reviewer passes | n/a (moderator re-selects speakers) | n/a (read-only until finalize) | invalid speaker or model down -> deterministic speaker policy | max rounds, repeated review issues, missing evidence worker or budget -> referral |
| `magentic` | progress ledger reports the request satisfied after a passed review | stall or failed assignee -> replan (at most once) | n/a (read-only until finalize) | invalid ledger or speaker -> deterministic ledger; failed worker's task moves to another capable agent | stalled after replan, no capable agent for a task, or budget -> referral |
| `blackboard` | control fires eligible sources until the review on the board passes | a failed review makes the drafter eligible again | n/a (read-only until finalize) | failed analyst -> researcher's ratio calculator posts the analysis | no eligible source, repeated review issues or budget -> referral |
| `human_gate` | no referral, or a credit officer decides the referred file | n/a | n/a | n/a | is the human gate (interrupt with reason, citations and memo) |
| `finalize` | completed memo filed once (idempotency key per loan, pattern and decision) | gateway backoff on the filing call | n/a (filing is a record, not a funding action) | n/a | loan system down at filing -> memo not filed, recorded for the underwriter |
<!-- /output -->

Chaos scenarios asserted in `tests/test_chaos.py`:

<!-- output-md: python scripts/doc_tables.py 21 chaos -->
| Injected fault (`CHAOS_FAULTS`) | Node | Expected exit | Invariant asserted |
|---|---|---|---|
| `model` | `supervisor` | **degrade** | every worker and the router take their deterministic path; zero LLM calls; correct decision filed once |
| `sor:loan_system` | `swarm` | **escalate** | researcher cannot read the file -> swarm refers the case; nothing filed |
| `retrieval` | `magentic` | **escalate** | policy agent fails; replan finds no capable agent for rules -> referral; nothing filed |
| `jailbreak` | `group_chat` | **degrade** | injected borrower note neutralised by the gateway; decision unchanged; no injected text in memo or trace |
<!-- /output -->

### Failure handling

| Failure | What happens |
|---|---|
| Model down (all deployments) | Every worker and router takes its deterministic path (zero LLM calls), the memo is still reviewed and filed once (chaos: `model`) |
| Loan system down | The researcher fails; the swarm has nobody else to route to and refers the file; nothing filed (chaos: `sor:loan_system`) |
| Policy retrieval down | The policy agent fails; magentic replans, finds no other agent with the `rules` capability and refers (chaos: `retrieval`) |
| Injected text in the borrower note | The MCP gateway neutralises it before any agent sees it; the decision is unchanged and no injected text reaches the memo or trace (chaos: `jailbreak`) |
| Worker down, looping reviewer, bad handoff | See the fault table: recovered or safe stop, never a wrong decision |
| Budget exhausted | `budget_exhausted:turns / llm_calls / tokens` referral |
| Referral of any kind | `human_gate` pauses at `interrupt()`; the credit officer's decision is recorded (`decided_by`) and filed |

## 14. Mapping to Azure services

Nothing here is deployed. This is how each piece would map onto Azure:

<!-- output-md: python scripts/doc_tables.py 21 azure -->
| Piece | Azure service it maps to |
|---|---|
| Model calls | Azure OpenAI in Microsoft Foundry, keyless through `DefaultAzureCredential` (`shared/llm.py`), with a fallback deployment behind a circuit breaker |
| Agent runtime | Azure Container Apps (the `orchestration_lab.graph:build_graph` graph runs inside the portfolio API image); LangGraph checkpoints in Azure Database for PostgreSQL |
| Corpus `credit-policy` | Azure AI Search index with security-trimming filters for the ACL and `valid_from`/`valid_to` fields; sensitivity `internal` as a Microsoft Purview label |
| Loan origination system | MCP server on Azure Container Apps (or Azure Functions), published through Azure API Management; called with the tool identity's managed identity |
| Credit bureau | MCP server on Azure Container Apps (or Azure Functions), published through Azure API Management; called with the tool identity's managed identity |
| Tool identities | One user-assigned managed identity per row of the identity table, scoped with Azure RBAC; Microsoft Entra Agent ID when it applies |
| Traces and cost | Application Insights through the Azure Monitor OpenTelemetry exporter (`OTEL_EXPORTER_OTLP_ENDPOINT`) |
| Eval gate | Microsoft Foundry evaluations for the live model, with the same thresholds as `doctrine.yaml`; GitHub Actions blocks promotion |
| Guardrails and policy | Azure AI Content Safety (prompt shields) in front of the model; Azure Policy for private networking and tags; Key Vault for any secret |
<!-- /output -->

## 15. Limitations

<!-- output-md: python scripts/doc_tables.py 21 status -->
Maturity (self-rated in `doctrine.yaml`): **Level 3**, every pattern shares least-privilege MCP identities, as-of policy retrieval with ACL, a deterministic critic, budgets and a human gate for referrals; comparison numbers are regenerated from runs and gated in CI. Next rung: run the comparison against a real model deployment on a larger sampled set and promote the chosen pattern behind the control-plane registry (project 12) with per-pattern kill switches.
<!-- /output -->

- Runs against a deterministic mock model, mock systems of record and synthetic data, so the eval scores measure the graph, retrieval and policies, not a live model's quality.
- The real-model path has not been exercised against a live Azure OpenAI deployment.
- Checkpoints use the in-memory saver; a production run needs a durable checkpointer.
- KPI targets are design targets; nothing has been measured in production.

## 16. Interview talking points

1. **Topology is a cost/control trade, and I can show the curve.** Same task, same workers:
   the one-pass patterns are cheapest but can't fix a draft; the swarm and blackboard get full
   quality at near-pipeline cost; supervisor and hierarchical buy central control with a
   routing call per step; group chat pays for shared context; magentic pays for replanning.
2. **Controls belong in a harness, not in each pattern.** Budgets, loop detection, route
   validation, termination, tracing and HITL are shared, so a comparison measures topology.
3. **Failure behaviour is the real differentiator.** With one worker down only the patterns
   that plan by capability (magentic, blackboard) recover; the rest must refer, and none may
   guess. That is tested cell by cell.
4. **LLM proposes, code disposes.** Routes, handoffs, speakers, ledgers and policy mappings are
   validated; numbers and limits come from code keyed by cited policy ids.
5. **Numbers in docs are generated.** The README table is written by the runner and a test
   fails if it drifts.

## 17. Adopt this

How another team reuses this project:

1. **Copy the pattern, keep the platform.** Copy `projects/21-multi-agent-orchestration-patterns/`, rename the `orchestration_lab` package and add it to `pythonpath` in `pyproject.toml`. Keep `shared/` as a dependency: it supplies the model factory, context builder, tool gateway, resilience and tracing.
2. **Point it at your systems.** Each system of record in section 11 sits behind a tool contract; swap the mock MCP server in `shared/mcp_servers` for yours with the same tool names and schemas, and give each tool identity in section 10 its own managed identity.
3. **Configure it in `doctrine.yaml`.** Thresholds, stop conditions, KPIs, identities and chaos scenarios live in the card; `python -m shared.doctrine validate` refuses a card with gaps.
4. **Bring your own golden set.** Replace `evals/golden.jsonl` with cases from your domain (same fields) and run `python -m evals --project 21`; CI blocks promotion when a threshold is missed.
5. **Extend it safely.** Add a node in `build_graph`, then add its five-exit row to `failure_playbook` and a chaos scenario if it can fail; the validator fails until the row exists.
6. **Turn on a real model** with `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_DEPLOYMENT` (keyless). Routing stays in code, so control flow does not change; run `python -m evals --project 21 --live` before trusting the wording.
7. **Keep the docs honest.** Run `python scripts/render_docs.py` after a change; CI fails when the pasted output or excerpts in this README drift.
