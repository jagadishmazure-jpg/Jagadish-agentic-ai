"""Blackboard: agents are knowledge sources that fire when their preconditions are on the board.

There is no routing model. A deterministic control component inspects the shared board (the
workspace) each cycle and fires **every** eligible knowledge source in parallel (``Send``):
researcher and policy in cycle one, analyst next, then drafter, then reviewer. A failed review
makes the drafter eligible again. Opportunistic control also gives a natural fallback: if the
analyst fails, the researcher (which carries the ratio calculator) becomes eligible to post
the analysis.

Stops when the review passes, when no source is eligible, when the same review issues come back
(no progress) or on the harness budgets.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from orchestration_lab import routing
from orchestration_lab.agents import WORKERS
from orchestration_lab.harness import Harness
from orchestration_lab.patterns import finish_node
from orchestration_lab.state import PatternState


def eligible(ws: dict[str, Any]) -> list[tuple[str, str]]:
    """(knowledge source, task) pairs whose preconditions hold and whose output is missing."""
    failed = set(routing.failed(ws))
    out: list[tuple[str, str]] = []
    if not ws.get("facts") and "researcher" not in failed:
        out.append(("researcher", "facts"))
    if not ws.get("rules") and "policy" not in failed:
        out.append(("policy", "rules"))
    if ws.get("facts") and not ws.get("analysis"):
        if "analyst" not in failed:
            out.append(("analyst", "analysis"))
        elif "researcher" not in failed:
            out.append(("researcher", "analysis"))  # capability fallback
    if routing.ready("drafter", ws) and "drafter" not in failed:
        d, r = ws.get("draft"), ws.get("review")
        if not d or (r and r["revision"] == d["revision"] and not r["passed"]):
            out.append(("drafter", "draft"))
    if ws.get("draft") and not routing.reviewed_current(ws) and "reviewer" not in failed:
        out.append(("reviewer", "review"))
    return out


def build(h: Harness):
    g = StateGraph(PatternState)

    def control(state: dict[str, Any]) -> dict[str, Any]:
        c = dict(state.get("control") or {})
        ws = state.get("ws", {})
        history = list(c.get("reviews", []))
        if ws.get("review") and c.get("seen_review") != ws["review"]["revision"]:
            history.append(list(ws["review"]["issues"]))
            c["seen_review"] = ws["review"]["revision"]
        c["reviews"] = history
        update = h.code_step(state, "control")
        if ws.get("review") and ws["review"]["passed"] and routing.reviewed_current(ws):
            return {**update, "control": {**c, "fire": []}}
        stop = h.guard(state)
        if not stop and h.repeated_review(ws, history):
            stop = "no_progress"
        fire = eligible(ws) if not stop else []
        if not stop and not fire:
            stop = (
                f"worker_failed:{routing.failed(ws)[0]}"
                if routing.failed(ws)
                else "no_eligible_source"
            )
        return {**update, "control": {**c, "fire": fire, "stop": stop}}

    def route(state: dict[str, Any]):
        fire = state["control"]["fire"]
        if not fire:
            return "finish"
        return [
            Send(agent, {**state, "control": {**state["control"], "task": task}})
            for agent, task in fire
        ]

    def ks(agent: str):
        def node(state: dict[str, Any]) -> dict[str, Any]:
            task = (state.get("control") or {}).get("task", "")
            kw = {"task": task} if agent == "researcher" else {}
            label = f"{agent}.{task}" if agent == "researcher" and task == "analysis" else agent
            return h.turn(agent, state, WORKERS[agent], label=label, **kw)[0]

        node.__name__ = agent
        return node

    g.add_node("controller", control)
    for agent in routing.WORKERS:
        g.add_node(agent, ks(agent))
        g.add_edge(agent, "controller")
    g.add_node("finish", finish_node(h))
    g.add_edge(START, "controller")
    g.add_conditional_edges("controller", route, [*routing.WORKERS, "finish"])
    g.add_edge("finish", END)
    return g.compile(name="blackboard")
