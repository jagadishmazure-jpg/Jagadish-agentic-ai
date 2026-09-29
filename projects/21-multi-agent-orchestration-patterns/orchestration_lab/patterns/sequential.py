"""Sequential pipeline: researcher -> analyst -> policy -> drafter -> reviewer.

Cheapest to reason about and to operate: fixed order, no routing model, one pass. The price is
that nothing can loop back: the reviewer can only pass the memo or refer the file to a human.
Any worker failure stops the pipeline.
"""

from __future__ import annotations

import itertools
from typing import Any

from langgraph.graph import END, START, StateGraph

from orchestration_lab import routing
from orchestration_lab.harness import Harness
from orchestration_lab.patterns import finish_node, worker_node
from orchestration_lab.state import PatternState

ORDER = ("researcher", "analyst", "policy", "drafter", "reviewer")


def build(h: Harness):
    g = StateGraph(PatternState)
    for agent in ORDER:
        g.add_node(agent, worker_node(h, agent))
    g.add_node("finish", finish_node(h))
    g.add_edge(START, ORDER[0])

    def after(nxt: str):
        def route(state: dict[str, Any]) -> str:
            return "finish" if routing.failed(state["ws"]) else nxt

        return route

    for a, b in itertools.pairwise(ORDER):
        g.add_conditional_edges(a, after(b), [b, "finish"])
    g.add_edge("reviewer", "finish")
    g.add_edge("finish", END)
    return g.compile(name="sequential")
