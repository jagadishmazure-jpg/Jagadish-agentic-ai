"""Hierarchical: a top supervisor delegates to team supervisors, each running a subgraph.

    top_supervisor --Send--> evidence_team (lead -> researcher, analyst)
                   --Send--> policy_team   (lead -> policy)
                   -------> decision_team (lead -> drafter <-> reviewer, one revision)

Each team is its own compiled ``StateGraph`` with a team lead (LLM router + guard). The top
supervisor only sees team-level status, so its context stays small as teams grow; the cost is
an extra layer of routing calls. Independent teams run in parallel. A failed member ends its
team, and the top supervisor refers the file rather than guessing.
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

TEAMS: dict[str, dict[str, list[str]]] = {
    "evidence_team": {
        "members": ["researcher", "analyst"],
        "needs": [],
        "deliverables": ["facts", "analysis"],
    },
    "policy_team": {"members": ["policy"], "needs": [], "deliverables": ["rules"]},
    "decision_team": {
        "members": ["drafter", "reviewer"],
        "needs": ["facts", "analysis", "rules"],
        "deliverables": ["draft", "review"],
    },
}
MAX_REVISIONS = 1
COUNTERS = ("llm_calls", "tokens", "tool_calls")


def _team_graph(h: Harness, team: str):
    spec = TEAMS[team]
    members = spec["members"]
    g = StateGraph(PatternState)

    def lead_turn(hh: Harness, state: dict[str, Any], m: Meter):
        ws = state.get("ws", {})
        st = routing.status(ws)
        expected = routing.next_step(st, order=tuple(members))
        expected = expected if expected in members else "DONE"
        resp = hh.ask(
            "team_lead",
            {"team": team, "members": members, "deliverables": spec["deliverables"], "status": st},
            m,
        )
        proposed = (resp or {}).get("next")
        ok = hh.valid_target(str(proposed), {*members, "DONE"}) and (
            proposed == "DONE" or routing.ready(str(proposed), ws)
        )
        exits = []
        if not ok:
            if resp is not None:
                exits.append(exit_record(hh.pattern, "degrade", f"{team} lead route rejected"))
            proposed = expected
        return {}, {"next": proposed, "exits": exits, "note": f"-> {proposed}"}

    def lead(state: dict[str, Any]) -> dict[str, Any]:
        control = dict(state.get("control") or {})
        ws = state.get("ws", {})
        base = control.get("base", {})
        budget_view = {
            **state,
            "turns": [None] * base.get("turns", 0) + state.get("turns", []),
            **{k: base.get(k, 0) + state.get(k, 0) for k in COUNTERS},
        }
        if stop := h.guard(budget_view):
            return {"control": {**control, "stop": stop, "next": "DONE"}}
        if failed := [a for a in routing.failed(ws) if a in members]:
            return {"control": {**control, "stop": f"worker_failed:{failed[0]}", "next": "DONE"}}
        update, info = h.turn(f"{team}.lead", state, lead_turn, label=f"{team}.lead")
        nxt = info.get("next") or "DONE"
        draft = ws.get("draft")
        if nxt == "drafter" and draft and draft["revision"] > MAX_REVISIONS:
            control["stop"] = "review_failed_after_revision"
            nxt = "DONE"
        update["control"] = {**control, "next": nxt}
        return update

    g.add_node("lead", lead)
    for a in members:
        g.add_node(a, worker_node(h, a))
        g.add_edge(a, "lead")
    g.add_edge(START, "lead")
    g.add_conditional_edges(
        "lead",
        lambda s: END if s["control"]["next"] == "DONE" else s["control"]["next"],
        [*members, END],
    )
    return g.compile(name=team)


def build(h: Harness):
    teams = {name: _team_graph(h, name) for name in TEAMS}
    g = StateGraph(PatternState)
    team_view = {
        k: {"needs": v["needs"], "deliverables": v["deliverables"]} for k, v in TEAMS.items()
    }

    def top_turn(hh: Harness, state: dict[str, Any], m: Meter):
        ws = state.get("ws", {})
        st = routing.status(ws)
        todo = routing.teams_todo(st, team_view)
        resp = hh.ask("supervisor", {"status": st, "teams": team_view}, m)
        proposed = hh.propose((resp or {}).get("next"))
        parallel = [t for t in (resp or {}).get("parallel") or [] if t in todo]
        exits = []
        if proposed == "FINISH" and not todo:
            return {}, {"next": ["FINISH"], "note": "FINISH"}
        if proposed not in todo:
            if resp is not None:
                exits.append(exit_record(hh.pattern, "degrade", f"top route {proposed!r} rejected"))
            proposed = todo[0] if todo else "FINISH"
            parallel = todo if len(todo) > 1 else []
        nxt = parallel if len(parallel) > 1 else [proposed]
        return {}, {"next": nxt, "exits": exits, "note": f"-> {nxt}"}

    def top(state: dict[str, Any]) -> dict[str, Any]:
        control = dict(state.get("control") or {})
        ws = state.get("ws", {})
        if stop := h.guard(state):
            return {"control": {**control, "stop": stop, "next": ["finish"]}}
        if failed := routing.failed(ws):
            reason = ws["errors"][failed[0]]
            reason = (
                reason
                if reason.startswith(("worker_failed", "budget", "review"))
                else (f"worker_failed:{failed[0]}")
            )
            return {"control": {**control, "stop": reason, "next": ["finish"]}}
        update, info = h.turn("top_supervisor", state, top_turn, label="top_supervisor")
        nxt = ["finish" if n == "FINISH" else n for n in info.get("next") or ["FINISH"]]
        update["control"] = {**control, "next": nxt}
        return update

    def team_node(name: str):
        def run_team(state: dict[str, Any]) -> dict[str, Any]:
            base = {"turns": len(state.get("turns", [])), **{k: state.get(k, 0) for k in COUNTERS}}
            sub_in = {
                "case": state["case"],
                "ws": state.get("ws", {}),
                "clock_ms": state.get("clock_ms", 0.0),
                "control": {"base": base},
            }
            out = teams[name].invoke(sub_in)
            ws = dict(out.get("ws", {}))
            if stop := out.get("control", {}).get("stop"):
                ws["errors"] = {**ws.get("errors", {}), name: stop}
            return {
                "ws": ws,
                "turns": out.get("turns", []),
                "exits": out.get("exits", []),
                "clock_ms": out.get("clock_ms", 0.0),
                **{k: out.get(k, 0) for k in COUNTERS},
            }

        run_team.__name__ = name
        return run_team

    def route(state: dict[str, Any]):
        nxt = state["control"]["next"]
        return [Send(t, state) for t in nxt] if len(nxt) > 1 else nxt[0]

    g.add_node("top_supervisor", top)
    for name in TEAMS:
        g.add_node(name, team_node(name))
        g.add_edge(name, "top_supervisor")
    g.add_node("finish", finish_node(h))
    g.add_edge(START, "top_supervisor")
    g.add_conditional_edges("top_supervisor", route, [*TEAMS, "finish"])
    g.add_edge("finish", END)
    return g.compile(name="hierarchical")
