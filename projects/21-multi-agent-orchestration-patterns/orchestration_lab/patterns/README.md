# `orchestration_lab/patterns/`: one module per orchestration pattern

Each module exposes `build(harness) -> compiled LangGraph graph` over `PatternState` and uses
the same workers from [`../agents.py`](../agents.py). All of them end in a `finish` node that
calls `Harness.finish()`, so "completed" always means a reviewer-passed memo and anything else
is a referral with a `stop_reason`.

| File | What it does |
|---|---|
| [`__init__.py`](__init__.py) | `worker_node` (one worker turn as a node), `finish_node`, `initial_state`. |
| [`sequential.py`](sequential.py) | Fixed pipeline researcher → analyst → policy → drafter → reviewer; any failure goes to `finish`; no loop back. |
| [`concurrent.py`](concurrent.py) | researcher ∥ policy ∥ analyst from `START`, `join`, then drafter → reviewer. The analyst reads the loan file itself (duplicate reads, shorter critical path). |
| [`supervisor.py`](supervisor.py) | LLM supervisor proposes the next worker (or a parallel pair via `Send`); the proposal is validated against the registry and prerequisites, falls back to `routing.next_step`; one retry per failed worker, one revision after a failed review. |
| [`hierarchical.py`](hierarchical.py) | Top supervisor routes three teams (evidence, policy, decision); each team is a compiled subgraph with its own LLM team lead. Independent teams run in parallel; budgets carry across the subgraph boundary. |
| [`swarm.py`](swarm.py) | Peer-to-peer handoffs with `Command(goto=...)`: the handoff target comes from the worker's own model call. Bad targets get one re-ask; ping-pong and budgets end the run. |
| [`group_chat.py`](group_chat.py) | Moderator (LLM + guard) picks speakers over a shared transcript: evidence workers, then advocate vs risk officer until consensus, then drafter and reviewer. Stops on success, max rounds, no progress, missing evidence worker or budget. |
| [`magentic.py`](magentic.py) | Manager with a task ledger (plan by capability) and a progress ledger per round; stall counter, one replan (failed agents excluded, tasks reassigned by capability), `no_capable_agent` and `stalled` stops. |
| [`blackboard.py`](blackboard.py) | Deterministic `controller` fires every knowledge source whose preconditions are on the board, in parallel; capability fallback (researcher posts the analysis if the analyst failed); `no_progress` stop. |

Diagrams: [`../../graphs/`](../../graphs/) (`python run.py --mermaid graph.mmd`).
