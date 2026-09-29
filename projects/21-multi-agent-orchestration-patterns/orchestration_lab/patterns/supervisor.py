"""Supervisor (router): one LLM supervisor picks the next worker after every turn.

LLM proposes, code disposes: the proposed route is checked against the agent registry and each
worker's prerequisites; an invalid or unparseable proposal falls back to the deterministic plan
(``routing.next_step``) and is recorded as a degrade exit. The supervisor may fan out
independent workers (researcher and policy) in one step with ``Send``. Guards: one retry per
failed worker, one revision after a failed review, and the harness budgets.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from orchestration_lab import routing
from orchestration_lab.harness import Harness, Meter
from orchestration_lab.patterns import finish_node, worker_node
from orchestration_lab.state import PatternState
from shared.resilience import exit_record

MAX_REVISIONS = 1
MAX_RETRIES = 1
INDEPENDENT = {"researcher", "policy"}


def plan(h: Harness, state: dict[str, Any], m: Meter) -> tuple[dict[str, Any], dict[str, Any]]:
    """The supervisor's turn: propose, validate, fall back."""
    ws = state.get("ws", {})
    st = routing.status(ws)
    expected = routing.next_step(st)
    resp = h.ask(
        "supervisor",
        {"status": st, "agents": list(routing.WORKERS), "allow_parallel": True},
        m,
    )
    proposed = h.propose((resp or {}).get("next"))
    exits = []
    allowed = {*routing.WORKERS, "FINISH"}
    ok = h.valid_target(proposed, allowed) and (
        (proposed == "FINISH" and st["review_passed"])
        or (proposed in routing.WORKERS and routing.ready(proposed, ws))
    )
    if not ok:
        if resp is not None:
            exits.append(exit_record(h.pattern, "degrade", f"route {proposed!r} rejected"))
        proposed = expected
    parallel = [a for a in (resp or {}).get("parallel") or [] if a in INDEPENDENT]
    nxt = parallel if len(parallel) > 1 and proposed in parallel else [proposed]
    return {}, {"next": nxt, "exits": exits, "note": f"route {nxt}"}


def build(h: Harness):
    g = StateGraph(PatternState)

    def supervisor(state: dict[str, Any]) -> dict[str, Any]:
        control = dict(state.get("control") or {})
        ws = state.get("ws", {})
        if stop := h.guard(state):
            return {"control": {**control, "stop": stop, "next": ["finish"]}}
        retries = dict(control.get("retries", {}))
        failed = routing.failed(ws)
        extra_exits: list[dict[str, str]] = []
        cleared: dict[str, str] = {}
        for agent in failed:
            if retries.get(agent, 0) >= MAX_RETRIES:
                return {
                    "control": {**control, "stop": f"worker_failed:{agent}", "next": ["finish"]}
                }
            retries[agent] = retries.get(agent, 0) + 1
            cleared[agent] = ""
            extra_exits.append(exit_record(h.pattern, "retry", f"{agent} failed; retrying once"))
        view = {**state, "ws": {**ws, "errors": {**ws.get("errors", {}), **cleared}}}
        update, info = h.turn("supervisor", view, plan)
        nxt = info.get("next") or ["finish"]
        if not info["ok"]:
            nxt = [routing.next_step(routing.status(view["ws"]))]
        if nxt == ["FINISH"]:
            nxt = ["finish"]
        draft = ws.get("draft")
        if nxt == ["drafter"] and draft and draft["revision"] > MAX_REVISIONS:
            control["stop"] = "review_failed_after_revision"
            nxt = ["finish"]
        update["ws"] = {**update["ws"], "errors": cleared} if cleared else update["ws"]
        update["exits"] = extra_exits + update["exits"]
        update["control"] = {**control, "retries": retries, "next": nxt}
        return update

    def route(state: dict[str, Any]):
        nxt = state["control"]["next"]
        if len(nxt) > 1:
            return [Send(a, state) for a in nxt]
        return nxt[0]

    g.add_node("supervisor", supervisor)
    for agent in routing.WORKERS:
        g.add_node(agent, worker_node(h, agent))
        g.add_edge(agent, "supervisor")
    g.add_node("finish", finish_node(h))
    g.add_edge(START, "supervisor")
    g.add_conditional_edges("supervisor", route, [*routing.WORKERS, "finish"])
    g.add_edge("finish", END)
    return g.compile(name="supervisor")
