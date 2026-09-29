"""Group chat / debate with a moderator.

All participants share one transcript and every speaker reads all of it (that is the point:
shared context, and the reason token use grows fastest here). A moderator (LLM + guard) picks
the next speaker. Evidence workers speak first; then the **advocate** (relationship manager)
and the **risk officer** debate the decision until the risk officer agrees; then the drafter
writes and the reviewer checks.

Termination conditions: the reviewer passes the memo (success), the moderator terminates,
``MAX_ROUNDS`` speaker turns, the same review issues coming back (no progress), a required
evidence worker being unavailable, or the harness budgets.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from orchestration_lab import domain, mock_llm, routing
from orchestration_lab.agents import WORKERS
from orchestration_lab.harness import Harness, Meter
from orchestration_lab.patterns import finish_node
from orchestration_lab.state import PatternState
from shared.resilience import exit_record

PARTICIPANTS = (
    "researcher",
    "analyst",
    "policy",
    "advocate",
    "risk_officer",
    "drafter",
    "reviewer",
)
MAX_ROUNDS = 16
EVIDENCE = ("researcher", "analyst", "policy")


def _need(ws: dict[str, Any]) -> None:
    if not (ws.get("facts") and ws.get("rules")):
        from orchestration_lab.harness import MissingInputError

        raise MissingInputError("debate needs facts and rules")


def advocate(h: Harness, state: dict[str, Any], m: Meter) -> tuple[dict, dict]:
    ws = state.get("ws", {})
    _need(ws)
    resp = h.ask("advocate", {"facts": ws["facts"], "rules": ws["rules"]}, m)
    prop = (resp or {}).get("proposal")
    if not isinstance(prop, dict) or prop.get("decision") not in domain.DECISIONS:
        d = domain.decide(ws["facts"], ws["rules"])  # model down: state the policy position
        prop = {"decision": d.decision, "conditions": d.conditions}
    return {"proposal": prop}, {"say": {"proposal": prop}, "note": f"proposes {prop['decision']}"}


def risk_officer(h: Harness, state: dict[str, Any], m: Meter) -> tuple[dict, dict]:
    ws = state.get("ws", {})
    _need(ws)
    prop = ws.get("proposal") or {}
    resp = h.ask("risk_officer", {"facts": ws["facts"], "rules": ws["rules"], "proposal": prop}, m)
    d = domain.decide(ws["facts"], ws["rules"])
    counter = {"decision": d.decision, "conditions": d.conditions}
    if resp is None or not isinstance(resp.get("agree"), bool):
        agree = prop.get("decision") == d.decision and sorted(
            prop.get("conditions") or []
        ) == sorted(d.conditions)
        resp = {"agree": agree, "counter": counter}
    say = {"agree": resp["agree"], "counter": resp.get("counter") or counter}
    update = {"consensus": prop} if resp["agree"] else {}
    return update, {"say": say, "note": "agrees" if resp["agree"] else "objects"}


SPEAKERS = {**WORKERS, "advocate": advocate, "risk_officer": risk_officer}


def build(h: Harness):
    g = StateGraph(PatternState)

    def moderator_turn(hh: Harness, state: dict[str, Any], m: Meter):
        ws = state.get("ws", {})
        st = routing.status(ws)
        payload = {
            "status": st,
            "participants": list(PARTICIPANTS),
            "transcript": state.get("transcript", []),
            "consensus": ws.get("consensus"),
        }
        resp = hh.ask("moderator", payload, m)
        exits = []
        rule = mock_llm.moderator(payload)  # deterministic speaker policy (fallback + guard)
        if resp is None:
            resp = rule
        speaker = hh.propose(resp.get("next_speaker")) if not resp.get("terminate") else ""
        if resp.get("terminate") and not st["review_passed"]:
            resp = rule  # may only terminate on success; otherwise the harness stops the chat
        elif not resp.get("terminate") and not (
            hh.valid_target(speaker, set(PARTICIPANTS)) and speaker not in st["failed_agents"]
        ):
            exits.append(exit_record(hh.pattern, "degrade", f"speaker {speaker!r} rejected"))
            resp = rule
            speaker = rule.get("next_speaker", "")
        return {}, {
            "terminate": bool(resp.get("terminate")),
            "speaker": speaker,
            "exits": exits,
            "note": "terminate" if resp.get("terminate") else f"-> {speaker}",
        }

    def moderator(state: dict[str, Any]) -> dict[str, Any]:
        control = dict(state.get("control") or {})
        ws = state.get("ws", {})
        history = list(control.get("reviews", []))
        if ws.get("review") and control.get("seen_review") != ws["review"]["revision"]:
            history.append(list(ws["review"]["issues"]))
            control["seen_review"] = ws["review"]["revision"]
        control["reviews"] = history
        rounds = sum(1 for t in state.get("turns", []) if t["agent"] in PARTICIPANTS)
        stop = h.guard(state)
        if not stop and rounds >= MAX_ROUNDS:
            stop = "max_rounds"
        if not stop and h.repeated_review(ws, history):
            stop = "no_progress"
        if not stop and (down := [a for a in EVIDENCE if a in routing.failed(ws)]):
            stop = f"worker_failed:{down[0]}"
        if stop:
            return {"control": {**control, "stop": stop, "next": "finish"}}
        update, info = h.turn("moderator", state, moderator_turn)
        stopped = info.get("terminate") or not info["ok"]
        nxt = "finish" if stopped else (info["speaker"] or "finish")
        update["control"] = {
            **control,
            "next": "finish" if nxt == "finish" else "speak",
            "speaker": nxt,
        }
        return update

    def speak(state: dict[str, Any]) -> dict[str, Any]:
        speaker = state["control"]["speaker"]
        update, info = h.turn(
            speaker, state, SPEAKERS[speaker], extra={"transcript": state.get("transcript", [])}
        )
        content = info.get("say") or {"note": info.get("note", ""), "ok": info["ok"]}
        update["transcript"] = [{"speaker": speaker, "content": content}]
        return update

    g.add_node("moderator", moderator)
    g.add_node("speak", speak)
    g.add_node("finish", finish_node(h))
    g.add_edge(START, "moderator")
    g.add_conditional_edges("moderator", lambda s: s["control"]["next"], ["speak", "finish"])
    g.add_edge("speak", "moderator")
    g.add_edge("finish", END)
    return g.compile(name="group_chat")
