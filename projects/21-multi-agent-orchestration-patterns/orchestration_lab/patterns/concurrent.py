"""Concurrent fan-out / fan-in: researcher || policy || analyst, then drafter -> reviewer.

The three evidence workers start in the same super-step. The analyst does not wait for the
researcher: it reads the loan file through its own scoped gateway (duplicate tool calls,
shorter critical path). ``clock_ms`` keeps the max of the branches, so the reported latency is
the slowest branch, not the sum. Like the pipeline, there is no feedback loop.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from orchestration_lab import routing
from orchestration_lab.harness import Harness
from orchestration_lab.patterns import finish_node, worker_node
from orchestration_lab.state import PatternState

BRANCHES = ("researcher", "policy", "analyst")


def build(h: Harness):
    g = StateGraph(PatternState)
    for agent in (*BRANCHES, "drafter", "reviewer"):
        g.add_node(agent, worker_node(h, agent))

    def join(state: dict[str, Any]) -> dict[str, Any]:
        return h.code_step(state, "join")

    g.add_node("join", join)
    g.add_node("finish", finish_node(h))
    for b in BRANCHES:
        g.add_edge(START, b)
        g.add_edge(b, "join")  # all branches finish in one super-step -> join runs once
    g.add_conditional_edges(
        "join", lambda s: "finish" if routing.failed(s["ws"]) else "drafter", ["drafter", "finish"]
    )
    g.add_conditional_edges(
        "drafter",
        lambda s: "finish" if routing.failed(s["ws"]) else "reviewer",
        ["reviewer", "finish"],
    )
    g.add_edge("reviewer", "finish")
    g.add_edge("finish", END)
    return g.compile(name="concurrent")
