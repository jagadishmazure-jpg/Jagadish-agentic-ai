"""Arena graph: one entry point that runs the loan-exception task through any pattern.

    intake -> <pattern> -> human_gate -> finalize

* ``intake`` loads the exception ticket (unknown loans are rejected).
* ``<pattern>`` is one node per orchestration pattern (``sequential``, ``concurrent``,
  ``supervisor``, ``hierarchical``, ``swarm``, ``group_chat``, ``magentic``, ``blackboard``).
  Each node builds that pattern's own LangGraph graph inside a fresh ``Harness`` and invokes it.
* ``human_gate`` is the shared HITL hook: any referral (policy escalation or a safety stop)
  pauses at ``interrupt()`` for a credit officer when ``hitl=True``.
* ``finalize`` files the memo in the loan system (orchestrator identity, idempotent) for
  completed runs and returns the ``final`` report with the per-agent trace and metrics.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from orchestration_lab import domain
from orchestration_lab.harness import Budgets, FaultPlan, Harness
from orchestration_lab.patterns import (
    blackboard,
    concurrent,
    group_chat,
    hierarchical,
    initial_state,
    magentic,
    sequential,
    supervisor,
    swarm,
)
from orchestration_lab.sor import LoanSystems, gateways
from orchestration_lab.state import ArenaState
from shared.observability import install
from shared.resilience import exit_record
from shared.tools import SystemOfRecordUnavailableError

PATTERNS = {
    "sequential": sequential,
    "concurrent": concurrent,
    "supervisor": supervisor,
    "hierarchical": hierarchical,
    "swarm": swarm,
    "group_chat": group_chat,
    "magentic": magentic,
    "blackboard": blackboard,
}
DEFAULT_PATTERN = "supervisor"


def summarize(out: dict[str, Any]) -> dict[str, Any]:
    turns = out.get("turns", [])
    return {
        "llm_calls": out.get("llm_calls", 0),
        "tokens": out.get("tokens", 0),
        "tool_calls": out.get("tool_calls", 0),
        "turns": len(turns),
        "sim_latency_ms": round(out.get("clock_ms", 0.0), 1),
        "trace": turns,
        "transcript_len": len(out.get("transcript", [])),
    }


def run_pattern(
    pattern: str,
    loan_id: str,
    *,
    systems: LoanSystems | None = None,
    llm: BaseChatModel | None = None,
    budgets: Budgets | None = None,
    faults: FaultPlan | None = None,
) -> dict[str, Any]:
    """Run one pattern graph directly (no arena, no HITL) and return its final state."""
    h = Harness(pattern, systems=systems, llm=llm, budgets=budgets, faults=faults)
    return PATTERNS[pattern].build(h).invoke(initial_state(domain.ticket(loan_id)))


def build_graph(
    *,
    systems: LoanSystems | None = None,
    llm: BaseChatModel | None = None,
    budgets: Budgets | None = None,
    faults: FaultPlan | None = None,
    hitl: bool = True,
    checkpointer: Any = None,
):
    install()
    systems = systems or LoanSystems()
    filer = gateways(systems)["filer"]
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
