"""Magentic-style orchestration: a manager with a task ledger and a progress ledger.

Modelled on the Magentic-One design (outer loop: task ledger; inner loop: progress ledger):

1. **Task ledger** (one model call): facts given, facts to look up, and a plan that assigns each
   task to an agent whose *capabilities* cover it (``routing.CAPABILITIES``).
2. **Progress ledger** (one model call per round): is the request satisfied? are we in a loop?
   is progress being made? who speaks next, with what instruction?
3. **Stall detection**: no progress or a loop increments a stall counter (progress decrements
   it). Above ``MAX_STALLS`` the manager **replans** (new task ledger, failed agents excluded);
   after ``MAX_RESETS`` replans the run ends as ``stalled``.
4. A worker failure is a stall, and if the ledger's next assignee has failed the manager
   replans at once, which can move the task to another capable agent (the researcher also
   carries the ratio calculator).

Most flexible pattern, and the most model calls: the manager runs before every worker turn.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from orchestration_lab import mock_llm, routing
from orchestration_lab.agents import WORKERS
from orchestration_lab.harness import Harness, Meter
from orchestration_lab.patterns import finish_node
from orchestration_lab.state import PatternState
from shared.resilience import exit_record

MAX_STALLS = 2
MAX_RESETS = 1


def _plan(hh: Harness, state: dict[str, Any], m: Meter):
    ws = state.get("ws", {})
    payload = {
        "loan_id": state["case"]["loan_id"],
        "capabilities": {a: list(c) for a, c in routing.CAPABILITIES.items()},
        "failed_agents": routing.failed(ws),
    }
    resp = hh.ask("manager_plan", payload, m)
    rule = mock_llm.manager_plan(payload)  # deterministic ledger (fallback + validation)
    failed = set(payload["failed_agents"])
    plan = (resp or {}).get("plan") or []
    valid = [
        s
        for s in plan
        if isinstance(s, dict)
        and s.get("agent") in routing.CAPABILITIES
        and s.get("task") in routing.CAPABILITIES[s["agent"]]
        and s["agent"] not in failed
    ]
    exits = []
    if [s["task"] for s in valid] != [s["task"] for s in rule["plan"]]:
        if resp is not None:
            exits.append(exit_record(hh.pattern, "degrade", "task ledger invalid; rule plan"))
        valid = rule["plan"]
    ledger = {**(resp or rule), "plan": valid}
    return {}, {"ledger": ledger, "exits": exits, "note": f"plan {[s['agent'] for s in valid]}"}


def _progress(hh: Harness, state: dict[str, Any], m: Meter, loop_signal: bool, progressed: bool):
    ws = state.get("ws", {})
    plan = state["control"]["ledger"]["plan"]
    payload = {
        "status": routing.status(ws),
        "plan": plan,
        "loop_signal": loop_signal,
        "last_turn_progress": progressed,
    }
    resp = hh.ask("manager_progress", payload, m)
    rule = mock_llm.manager_progress(payload)
    exits = []
    if resp is None:
        resp = rule
    speaker = hh.propose(resp.get("next_speaker")) if not resp.get("is_request_satisfied") else ""
    if resp.get("is_request_satisfied") and not payload["status"]["review_passed"]:
        resp, speaker = rule, rule["next_speaker"]
    elif not resp.get("is_request_satisfied") and not hh.valid_target(
        speaker, {s["agent"] for s in plan}
    ):
        exits.append(exit_record(hh.pattern, "degrade", f"next speaker {speaker!r} rejected"))
        resp, speaker = {**rule, "is_progress_being_made": False}, rule["next_speaker"]
    task = next((s["task"] for s in plan if s["agent"] == speaker), "")
    if speaker == "researcher" and "facts" in routing.status(ws)["have"]:
        task = "analysis"
    return {}, {
        "ledger": {**resp, "next_speaker": speaker, "task": task},
        "exits": exits,
        "note": "satisfied" if resp.get("is_request_satisfied") else f"-> {speaker} ({task})",
    }


def _uncovered(ledger: dict[str, Any]) -> str:
    """First task in the ledger's plan with no capable, healthy agent ('' if all covered)."""
    tasks = {s["task"] for s in ledger["plan"]}
    return next((t for t in routing.TASK_ORDER if t not in tasks), "")


def build(h: Harness):
    g = StateGraph(PatternState)

    def manager(state: dict[str, Any]) -> dict[str, Any]:
        control = dict(state.get("control") or {})
        ws = state.get("ws", {})
        if stop := h.guard(state):
            return {"control": {**control, "stop": stop, "next": "finish"}}
        turns = state.get("turns", [])
        update: dict[str, Any] = {
            "turns": [],
            "exits": [],
            "llm_calls": 0,
            "tokens": 0,
            "tool_calls": 0,
            "clock_ms": state.get("clock_ms", 0.0),
        }

        def run(fn, label, **kw):
            nonlocal state
            u, info = h.turn("manager", state, fn, label=label, **kw)
            for k in ("turns", "exits"):
                update[k] = update[k] + u[k]
            for k in ("llm_calls", "tokens", "tool_calls"):
                update[k] += u[k]
            update["clock_ms"] = u["clock_ms"]
            state = {**state, "clock_ms": u["clock_ms"]}
            return info

        if "ledger" not in control:
            control["ledger"] = run(_plan, "manager.plan")["ledger"]
            control.update(stalls=0, resets=0, reviews=[])
        if gap := _uncovered(control["ledger"]):
            update["control"] = {**control, "stop": f"no_capable_agent:{gap}", "next": "finish"}
            return update
        # loop / progress signals from the last worker turn
        history = list(control.get("reviews", []))
        if ws.get("review") and control.get("seen_review") != ws["review"]["revision"]:
            history.append(list(ws["review"]["issues"]))
            control["seen_review"] = ws["review"]["revision"]
        control["reviews"] = history
        last = next((t for t in reversed(turns) if not t["agent"].startswith("manager")), None)
        progressed = bool(last is None or last["ok"])
        loop_signal = h.repeated_review(ws, history) or h.ping_pong(
            [t for t in turns if not t["agent"].startswith("manager")]
        )
        state = {**state, "control": control}
        info = run(_progress, "manager.progress", loop_signal=loop_signal, progressed=progressed)
        led = info["ledger"]
        if led.get("is_request_satisfied"):
            update["control"] = {**control, "next": "finish"}
            return update
        stalled = (not led.get("is_progress_being_made", True)) or led.get("is_in_loop")
        control["stalls"] = control["stalls"] + 1 if stalled else max(0, control["stalls"] - 1)
        failed = set(routing.failed(ws))
        must_replan = led["next_speaker"] in failed or not led["next_speaker"]
        if control["stalls"] > MAX_STALLS or must_replan:
            control["resets"] += 1
            if control["resets"] > MAX_RESETS:
                update["control"] = {**control, "stop": "stalled", "next": "finish"}
                return update
            update["exits"].append(exit_record(h.pattern, "retry", "replanning (stall or failure)"))
            state = {**state, "control": control}
            control["ledger"] = run(_plan, "manager.replan")["ledger"]
            control["stalls"] = 0
            if gap := _uncovered(control["ledger"]):
                update["control"] = {**control, "stop": f"no_capable_agent:{gap}", "next": "finish"}
                return update
            state = {**state, "control": control}
            led = run(_progress, "manager.progress", loop_signal=False, progressed=True)["ledger"]
            if led.get("is_request_satisfied") or not led["next_speaker"]:
                stop = None if led.get("is_request_satisfied") else "no_capable_agent"
                update["control"] = {**control, "stop": stop, "next": "finish"}
                return update
        update["control"] = {
            **control,
            "next": "worker",
            "speaker": led["next_speaker"],
            "task": led.get("task", ""),
        }
        return update

    def worker(state: dict[str, Any]) -> dict[str, Any]:
        c = state["control"]
        speaker = c["speaker"]
        kw = {"task": c["task"]} if speaker == "researcher" and c.get("task") else {}
        update, _ = h.turn(speaker, state, WORKERS[speaker], **kw)
        if update["turns"][-1]["ok"] and speaker in routing.failed(state.get("ws", {})):
            update["ws"] = {**update["ws"], "errors": {speaker: ""}}
        return update

    g.add_node("manager", manager)
    g.add_node("worker", worker)
    g.add_node("finish", finish_node(h))
    g.add_edge(START, "manager")
    g.add_conditional_edges("manager", lambda s: s["control"]["next"], ["worker", "finish"])
    g.add_edge("worker", "manager")
    g.add_edge("finish", END)
    return g.compile(name="magentic")
