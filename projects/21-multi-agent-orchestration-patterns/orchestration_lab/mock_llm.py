"""Deterministic offline model: one rule-based responder per role.

It only sees what a real model would see (system prompt + JSON payload) and answers with JSON.
Two scripted imperfections mirror failure modes seen with real models, so the patterns have
something to disagree about:

* the **drafter** drops ``employment_reverification`` from a first draft that has three or more
  conditions (omission under a long list); it fixes the memo when a reviewer issue names it.
* the **advocate** (group chat) opens with a borrower-friendly proposal and concedes only when
  the risk officer objects.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from langchain_core.messages import BaseMessage

from orchestration_lab import domain, routing

FLAW_CONDITION = "employment_reverification"


def _payload(messages: Sequence[BaseMessage]) -> dict[str, Any]:
    try:
        return json.loads(str(messages[-1].content))
    except (json.JSONDecodeError, IndexError):
        return {}


def _handoff(p: dict[str, Any]) -> str | None:
    if "status" not in p or "peers" not in p:
        return None
    nxt = routing.next_step(p["status"])
    return "END" if nxt == "FINISH" else nxt


def _decision(p: dict[str, Any]) -> domain.Decision:
    return domain.decide(p["facts"], p["rules"])


def researcher(p: dict[str, Any]) -> dict[str, Any]:
    lf = p.get("loan_file", {})
    return {
        "summary": f"Loan {lf.get('loan_id')} applied {lf.get('app_date')}; file, appraisal and "
        "credit summary retrieved.",
        "handoff_to": _handoff(p),
    }


def analyst(p: dict[str, Any]) -> dict[str, Any]:
    r = p["ratios"]
    return {
        "summary": f"DTI {r['dti']}%, LTV {r['ltv']}%, credit score {int(r['fico'])}.",
        "factors": p.get("candidate_factors", []),
        "handoff_to": _handoff(p),
    }


def policy(p: dict[str, Any]) -> dict[str, Any]:
    rules = {}
    for ev in p.get("evidence", []):
        t = domain.topic_of(ev["id"])
        if t and t not in rules:
            rules[t] = ev["id"]
    return {"rules": rules, "handoff_to": _handoff(p)}


def drafter(p: dict[str, Any]) -> dict[str, Any]:
    d = _decision(p).as_dict()
    feedback = " ".join(p.get("feedback") or [])
    if len(d["conditions"]) >= 3 and FLAW_CONDITION not in feedback:
        d["conditions"] = [c for c in d["conditions"] if c != FLAW_CONDITION]
    memo = domain.render_memo(p["loan_id"], p["facts"], d, p["rules"])
    return {
        "decision": d["decision"],
        "conditions": d["conditions"],
        "citations": d["citations"],
        "memo": memo,
        "handoff_to": _handoff(p),
    }


def supervisor(p: dict[str, Any]) -> dict[str, Any]:
    st = p["status"]
    if "teams" in p:  # top-level supervisor of a hierarchy routes teams, not workers
        todo = routing.teams_todo(st, p["teams"])
        nxt = todo[0] if todo else "FINISH"
        return {"next": nxt, "parallel": todo if len(todo) > 1 else [], "reason": f"{todo}"}
    nxt = routing.next_step(st)
    parallel = ["researcher", "policy"] if not st["have"] and p.get("allow_parallel") else []
    return {"next": nxt, "parallel": parallel, "reason": f"next missing: {nxt}"}


def team_lead(p: dict[str, Any]) -> dict[str, Any]:
    members = tuple(p["members"])
    st = p["status"]
    nxt = routing.next_step(st, order=members)
    delivered = set(p["deliverables"]) <= set(st["have"]) and (
        "review" not in p["deliverables"] or st["review_passed"]
    )
    done = nxt == "FINISH" or nxt not in members or delivered
    return {"next": "DONE" if done else nxt, "reason": "deliverable ready" if done else nxt}


def moderator(p: dict[str, Any]) -> dict[str, Any]:
    st = p["status"]
    if st["review_passed"]:
        return {"next_speaker": "", "terminate": True, "reason": "reviewer passed the memo"}
    for agent in ("researcher", "analyst", "policy"):
        if routing.PRODUCES[agent] not in st["have"] and agent not in st["failed_agents"]:
            return {"next_speaker": agent, "terminate": False, "reason": f"need {agent}"}
    if not p.get("consensus"):
        last = p["transcript"][-1]["speaker"] if p["transcript"] else ""
        nxt = "risk_officer" if last == "advocate" else "advocate"
        return {"next_speaker": nxt, "terminate": False, "reason": "debate the decision"}
    nxt = routing.next_step(st)
    return {"next_speaker": nxt, "terminate": False, "reason": f"consensus reached; {nxt}"}


def advocate(p: dict[str, Any]) -> dict[str, Any]:
    correct = _decision(p)
    objections = [m for m in p["transcript"] if m["speaker"] == "risk_officer"]
    if objections:  # concede to the latest counter-proposal
        counter = objections[-1]["content"].get("counter") or {}
        return {"proposal": counter, "argument": "Conceding to the policy position."}
    if correct.decision == "approve_with_conditions":
        conds = correct.conditions[:-1] if len(correct.conditions) > 1 else correct.conditions
        prop = {"decision": "approve_with_conditions", "conditions": conds}
    elif correct.decision in ("decline", "escalate"):
        prop = {"decision": "approve_with_conditions", "conditions": ["verify_reserves"]}
    else:
        prop = {"decision": correct.decision, "conditions": correct.conditions}
    return {"proposal": prop, "argument": "Strong relationship; the borrower qualifies."}


def risk_officer(p: dict[str, Any]) -> dict[str, Any]:
    correct = _decision(p)
    prop = p.get("proposal") or {}
    counter = {"decision": correct.decision, "conditions": correct.conditions}
    agree = prop.get("decision") == correct.decision and sorted(
        prop.get("conditions") or []
    ) == sorted(correct.conditions)
    return {
        "agree": agree,
        "counter": counter,
        "objection": ""
        if agree
        else f"Policy requires {counter['decision']} {counter['conditions']}",
    }


def manager_plan(p: dict[str, Any]) -> dict[str, Any]:
    failed = set(p.get("failed_agents", []))
    plan = []
    for task in routing.TASK_ORDER:
        able = [a for a, caps in routing.CAPABILITIES.items() if task in caps and a not in failed]
        able.sort(key=lambda a: routing.CAPABILITIES[a].index(task))  # primary skill first
        agent = able[0] if able else None
        if agent:
            plan.append({"task": task, "agent": agent})
    return {
        "facts_given": [f"exception ticket for {p['loan_id']}"],
        "facts_to_lookup": ["loan file", "appraisal", "credit score", "policy in force"],
        "plan": plan,
    }


def manager_progress(p: dict[str, Any]) -> dict[str, Any]:
    st = p["status"]
    have = set(st["have"])
    satisfied = st["review_passed"]
    nxt, instr = "", ""
    if not satisfied:
        order = [s["agent"] for s in p["plan"]]
        tasks = {s["agent"]: s["task"] for s in p["plan"]}
        for step in p["plan"]:
            task, agent = step["task"], step["agent"]
            if task == "review":
                if "draft" in have and st["review_revision"] != st["draft_revision"]:
                    nxt = agent
                    break
            elif task == "draft":
                if "draft" not in have or st["review_revision"] == st["draft_revision"]:
                    nxt = agent
                    break
            elif task not in have:
                nxt = agent
                break
        instr = f"{tasks.get(nxt, '')}" if nxt in order else ""
    return {
        "is_request_satisfied": satisfied,
        "is_in_loop": bool(p.get("loop_signal")),
        "is_progress_being_made": bool(p.get("last_turn_progress", True)),
        "next_speaker": nxt,
        "instruction": instr,
    }


def handoff(p: dict[str, Any]) -> dict[str, Any]:
    return {"handoff_to": _handoff(p) or "END"}


RESPONDERS = {
    "researcher": researcher,
    "analyst": analyst,
    "policy": policy,
    "drafter": drafter,
    "supervisor": supervisor,
    "team_lead": team_lead,
    "moderator": moderator,
    "advocate": advocate,
    "risk_officer": risk_officer,
    "manager_plan": manager_plan,
    "manager_progress": manager_progress,
    "handoff": handoff,
}


def respond(messages: Sequence[BaseMessage]) -> str:
    system = str(messages[0].content) if messages else ""
    role = system.split("\n", 1)[0].removeprefix("ROLE: ").strip()
    fn = RESPONDERS.get(role)
    if fn is None:
        return json.dumps({"error": f"unknown role {role}"})
    return json.dumps(fn(_payload(messages)), sort_keys=True)
