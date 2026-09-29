"""Handoff / swarm: peer-to-peer, no central boss.

Each agent does its work and, in the same model call, names the peer to hand off to; the node
returns ``Command(goto=peer)``. There are no routing-only model calls, which makes it the
cheapest dynamic pattern. The harness supplies what a boss would otherwise enforce:

* **handoff validation**: a target that is not a registered peer is rejected; the sender gets
  one re-ask (a small extra model call), and a second bad target ends the run;
* **ping-pong detection**: A-B-A-B-A-B between two agents ends the run;
* **budgets**, and a worker that is down ends the run (nobody else owns the route).
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from orchestration_lab import routing
from orchestration_lab.agents import WORKERS
from orchestration_lab.harness import Harness, Meter
from orchestration_lab.patterns import finish_node
from orchestration_lab.state import PatternState, merge_ws
from shared.resilience import exit_record

ENTRY = "researcher"


def peers_of(agent: str) -> list[str]:
    return [a for a in routing.WORKERS if a != agent] + ["END"]


def _repair(h: Harness, state: dict[str, Any], m: Meter, who: str):
    resp = h.ask(
        "handoff",
        {"agent": who, "peers": peers_of(who), "status": routing.status(state.get("ws", {}))},
        m,
    )
    return {}, {"handoff": (resp or {}).get("handoff_to"), "note": "handoff re-ask"}


def _add(update: dict[str, Any], more: dict[str, Any]) -> dict[str, Any]:
    out = dict(update)
    for k in ("turns", "exits"):
        out[k] = update.get(k, []) + more.get(k, [])
    for k in ("llm_calls", "tokens", "tool_calls"):
        out[k] = update.get(k, 0) + more.get(k, 0)
    out["clock_ms"] = max(update.get("clock_ms", 0.0), more.get("clock_ms", 0.0))
    out["ws"] = merge_ws(update.get("ws"), more.get("ws"))
    return out


def build(h: Harness):
    g = StateGraph(PatternState)

    def agent_node(agent: str):
        allowed = set(peers_of(agent))

        def node(state: dict[str, Any]) -> Command:
            control = dict(state.get("control") or {})
            if stop := h.guard(state):
                return Command(goto="finish", update={"control": {**control, "stop": stop}})
            update, info = h.turn(agent, state, WORKERS[agent], peers=peers_of(agent))
            if not info["ok"]:
                stop = f"worker_failed:{agent}"
                return Command(
                    goto="finish", update={**update, "control": {**control, "stop": stop}}
                )
            target = h.propose(info.get("handoff"))
            if not h.valid_target(target, allowed):
                bad = target
                after = {
                    **state,
                    "ws": merge_ws(state.get("ws"), update["ws"]),
                    "clock_ms": update["clock_ms"],
                }
                more, rinfo = h.turn(agent, after, _repair, who=agent, label=f"{agent}.handoff")
                more["exits"] = [
                    exit_record(h.pattern, "retry", f"{agent} handed off to {bad!r}; re-asked")
                ] + more["exits"]
                update = _add(update, more)
                target = h.propose(rinfo.get("handoff"))
                if not h.valid_target(target, allowed):
                    return Command(
                        goto="finish",
                        update={**update, "control": {**control, "stop": "bad_handoff"}},
                    )
            turns = [*state.get("turns", []), *update["turns"]]
            if target != "END" and h.ping_pong([*turns, {"agent": target}]):
                return Command(
                    goto="finish",
                    update={**update, "control": {**control, "stop": "ping_pong_detected"}},
                )
            goto = "finish" if target == "END" else target
            return Command(goto=goto, update={**update, "control": {**control, "active": target}})

        node.__name__ = agent
        return node

    for agent in routing.WORKERS:
        g.add_node(agent, agent_node(agent), destinations=(*routing.WORKERS, "finish"))
    g.add_node("finish", finish_node(h))
    g.add_edge(START, ENTRY)
    g.add_edge("finish", END)
    return g.compile(name="swarm")
