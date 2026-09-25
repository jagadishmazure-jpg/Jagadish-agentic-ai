"""Care graph for 'My shipment is late, can I get a refund?'

classify (confidence gate + fraud pre-route) -> plan (lanes + tool budget) -> order (OMS/CRM
via MCP) -> [policy (RAG as-of purchase date) || history (CRM cases, ACL-trimmed)] -> refund
(deterministic proposal + drafted reply) -> critic (repair once, then escalate) ->
human_approval (interrupt, SLA timer, deny/queue on timeout) -> finalize (outbox write,
honest status). Non-refund routes go to handoff.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt

from care_e2e import critic as critic_mod
from care_e2e import knowledge
from care_e2e import llm as ops
from care_e2e.policy import (
    CONFIDENCE_GATE,
    EDITIONS,
    HITL_SLA_HOURS,
    MAX_REPAIRS,
    decide,
)
from care_e2e.sor import build_gateways
from care_e2e.state import CareState
from care_e2e.systems import OrderNotFoundError, Systems, seed_systems, sla_due
from care_e2e.worker import dispatch
from shared.context import RetrievalError, looks_like_injection, sanitize
from shared.llm import get_llm
from shared.observability import install
from shared.resilience import exit_record, with_fallback
from shared.tools import SystemOfRecordUnavailableError

TIMEOUT_POLICY = "queue"  # or "deny": an expired approval never pays


def build_graph(
    systems: Systems | None = None,
    llm: BaseChatModel | None = None,
    checkpointer: Any = None,
    *,
    timeout_policy: str = TIMEOUT_POLICY,
):
    install()
    s = systems or seed_systems()
    model = with_fallback(llm or get_llm(mock_responder=ops.mock_responder))
    gws = build_gateways(s)
    reader, writer = gws["reader"], gws["writer"]
    kb = knowledge.builder()

    def over_budget(state: CareState, need: int) -> bool:
        cap = (state.get("plan") or {}).get("max_tool_calls", 99)
        return state.get("tool_calls", 0) + need > cap

    # ---------------------------------------------------------------- classify
    def classify(state: CareState) -> dict[str, Any]:
        req = state["request"]
        intent, degraded = ops.classify(model, req["message"])
        exits = []
        if degraded:
            exits.append(exit_record("classify", "degrade", "model down: keyword classifier"))
        calls, risk = 0, False
        try:  # fraud pre-route: CRM risk flag, before any refund tool is reachable
            calls += 1
            risk = bool(
                reader.call("crm", "get_account", account_id=req["customer_id"])["risk_flag"]
            )
        except SystemOfRecordUnavailableError:
            exits.append(exit_record("classify", "degrade", "CRM down: no risk flag; HITL later"))
        except KeyError:
            pass
        cue = any(w in req["message"].lower() for w in ("chargeback", "again and again"))
        if risk or cue:
            route = "fraud"
        elif intent.confidence < CONFIDENCE_GATE:
            route = "clarify"
        elif intent.intent not in ("refund_late", "wismo"):
            route = "human"
        else:
            route = "plan"
        return {
            "intent": intent.model_dump(),
            "fraud": risk or cue,
            "route": route,
            "tool_calls": calls,
            "needs_human": ["risk flag unavailable"] if exits and not degraded else [],
            "exits": exits,
            "trace": ["classify"],
        }

    # ---------------------------------------------------------------- plan
    def plan(state: CareState) -> dict[str, Any]:
        p, degraded, guarded = ops.plan(model, state["intent"]["intent"])
        exits = []
        if degraded:
            exits.append(exit_record("plan", "degrade", "model down: default plan"))
        elif guarded:
            exits.append(exit_record("plan", "degrade", "invalid plan: default plan"))
        return {"plan": p.model_dump(), "exits": exits, "trace": ["plan"]}

    # ---------------------------------------------------------------- order
    def order(state: CareState) -> Command:
        req, oid = state["request"], state["intent"].get("order_id")
        if not oid:
            return Command(goto="handoff", update={"route": "clarify", "trace": ["order"]})
        if over_budget(state, 2):
            return Command(
                goto="handoff",
                update={
                    "route": "budget",
                    "trace": ["order"],
                    "exits": [exit_record("order", "escalate", "tool budget exhausted")],
                },
            )
        try:
            ok = reader.call(
                "crm", "verify_customer", customer_id=req["customer_id"], email=req["email"]
            )["verified"]
            o = reader.call("oms", "get_order", order_id=oid)
        except OrderNotFoundError:
            ok, o = True, None
        except SystemOfRecordUnavailableError as exc:
            return Command(
                goto="handoff",
                update={
                    "route": "sor_down",
                    "tool_calls": 2,
                    "trace": ["order"],
                    "exits": [exit_record("order", "escalate", f"OMS/CRM down: {exc}")],
                },
            )
        if not ok or o is None or o["customer_id"] != req["customer_id"]:
            # never confirm that someone else's order exists
            return Command(
                goto="handoff", update={"route": "not_found", "tool_calls": 2, "trace": ["order"]}
            )
        lanes = state["plan"]["lanes"] if state["intent"]["intent"] == "refund_late" else []
        update = {"order": o, "tool_calls": 2, "trace": ["order"]}
        if not lanes:
            return Command(goto="refund", update=update)
        return Command(goto=[Send(lane, {**state, **update}) for lane in lanes], update=update)

    # ---------------------------------------------------------------- policy (knowledge plane)
    def policy(state: CareState) -> dict[str, Any]:
        o, req = state["order"], state["request"]
        as_of = date.fromisoformat(o["purchase_date"])
        try:
            b = kb.build(
                "late delivery refund policy shipment days late",
                knowledge.principal(req["tenant"]),
                as_of=as_of,
                k=4,
                kinds=["policy"],
            )
        except RetrievalError as exc:
            return {
                "policy": {"degraded": True, "chunk_ids": [], "edition": None},
                "needs_human": ["policy evidence unavailable"],
                "exits": [exit_record("policy", "degrade", f"{type(exc).__name__}: HITL")],
                "trace": ["policy"],
            }
        ids = b.chunk_ids
        edition = next((i.split("::")[0] for i in ids if i.split("::")[0] in EDITIONS), None)
        out: dict[str, Any] = {
            "policy": {
                "degraded": edition is None,
                "chunk_ids": ids,
                "edition": edition,
                "as_of": str(as_of),
                "dropped_acl": b.dropped_acl,
            },
            "citations": [i.split("::")[0] for i in ids],
            "trace": ["policy"],
        }
        if edition is None:
            out["needs_human"] = ["no late-delivery policy in force on purchase date"]
            out["exits"] = [exit_record("policy", "degrade", "edition not found: HITL")]
        return out

    # ---------------------------------------------------------------- history (CRM cases)
    def history(state: CareState) -> dict[str, Any]:
        req = state["request"]
        try:
            cases = reader.call("crm", "get_contact_history", account_id=req["customer_id"])
        except SystemOfRecordUnavailableError:
            return {
                "history": [],
                "tool_calls": 1,
                "exits": [exit_record("history", "degrade", "CRM down: no case history")],
                "trace": ["history"],
            }
        who = knowledge.principal(req["tenant"])
        visible = [c for c in knowledge.case_chunks(cases) if c.visible_to(who)]
        raw_injection = any(looks_like_injection(c["text"]) for c in cases)
        snippets = [{"case_id": c.chunk_id, "text": sanitize(c.text).text} for c in visible]
        injected = raw_injection or any("[removed:" in x["text"] for x in snippets)
        out: dict[str, Any] = {"history": snippets, "tool_calls": 1, "trace": ["history"]}
        if injected:
            out |= {
                "injection": True,
                "needs_human": ["instruction-like text in case history"],
                "exits": [exit_record("history", "escalate", "injection neutralised: HITL")],
            }
        return out

    # ---------------------------------------------------------------- refund (proposal + draft)
    def refund(state: CareState) -> dict[str, Any]:
        o, req = state["order"], state["request"]
        name = s.customers.get(req["customer_id"], {}).get("name", "there").split()[0]
        facts: dict[str, Any] = {
            "intent": state["intent"]["intent"],
            "first_name": name,
            "order_id": o["order_id"],
            "last_scan": o.get("last_scan"),
        }
        proposal = None
        if facts["intent"] == "refund_late":
            pol = state.get("policy") or {}
            edition = pol.get("edition") or (
                "CARE-LATE-2025" if o["purchase_date"] < "2026" else "CARE-LATE-2026"
            )
            proposal = decide(o, edition, s.today)
            if pol.get("degraded"):
                proposal["policy_id"] = None  # no evidence -> no citation claimed
            facts["proposal"] = proposal
        text, degraded = ops.draft(model, facts)
        exits = [exit_record("refund", "degrade", "model down: template reply")] if degraded else []
        return {
            "proposal": proposal,
            "facts": facts,
            "draft": text,
            "exits": exits,
            "trace": ["refund"],
        }

    # ---------------------------------------------------------------- critic
    def critic(state: CareState) -> Command:
        facts, text = state["facts"], state["draft"]
        issues, repairs, exits = critic_mod.check(text, facts), 0, []
        while issues and repairs < MAX_REPAIRS:
            repairs += 1
            text, degraded = ops.repair(model, facts, text, issues)
            exits.append(exit_record("critic", "retry", f"repair {repairs}: {issues[0]}"))
            if degraded:
                exits.append(exit_record("critic", "degrade", "model down: template repair"))
            issues = critic_mod.check(text, facts)
        needs = list(state.get("needs_human") or [])
        if issues:
            exits.append(exit_record("critic", "escalate", f"still failing: {issues[0]}"))
            needs.append(f"critic: {issues[0]}")
            text = ops.template_draft(facts)  # never send a failing draft
        p = state.get("proposal") or {}
        if p.get("needs_human"):
            needs.append("amount above auto-refund limit (CARE-AUTO-1)")
        update = {
            "draft": text,
            "critic": {"issues": issues, "repairs": repairs},
            "needs_human": needs,
            "exits": exits,
            "trace": ["critic"],
        }
        if p.get("eligible") and needs:
            return Command(goto="human_approval", update=update)
        return Command(goto="finalize", update=update)

    # ---------------------------------------------------------------- HITL with SLA
    def human_approval(state: CareState, config) -> dict[str, Any]:
        thread = config["configurable"]["thread_id"]
        due = sla_due(s.now, HITL_SLA_HOURS)
        s.pending_approvals.setdefault(thread, due)
        decision = interrupt(
            {
                "type": "refund_approval",
                "thread_id": thread,
                "proposal": state["proposal"],
                "draft": state["draft"],
                "reasons": state["needs_human"],
                "citations": sorted(set(state.get("citations", []))),
                "sla_due": due.isoformat(),
            }
        )
        s.pending_approvals.pop(thread, None)
        if decision.get("timeout"):
            action = timeout_policy
            exit_ = exit_record("human_approval", "escalate", f"SLA expired: {action}, no payment")
            return {
                "approval": {"decision": f"timeout_{action}"},
                "exits": [exit_],
                "trace": ["human_approval"],
            }
        approver = str(decision.get("approver", ""))
        ok = (
            decision.get("decision") == "approve"
            and approver
            and not approver.startswith(("mi-", "agent"))
        )
        return {
            "approval": {"decision": "approve" if ok else "deny", "approver": approver},
            "trace": ["human_approval"],
        }

    # ---------------------------------------------------------------- finalize
    def finalize(state: CareState) -> dict[str, Any]:
        req, p = state["request"], state.get("proposal") or {}
        text, appr = state["draft"], state.get("approval")
        key = f"refund:{state['order']['order_id']}"
        ticket = None
        exits = []
        if not p.get("eligible"):
            outcome = "status_update" if state["intent"]["intent"] == "wismo" else "not_eligible"
        elif appr and appr["decision"] == "deny":
            outcome = "denied"
            text = (
                f"Hi, we've reviewed order {state['order']['order_id']} and can't issue "
                "a refund on it right now. A specialist will contact you with details."
            )
        elif appr and appr["decision"].startswith("timeout"):
            ticket = s.outbox.put(key, {"order_id": state["order"]["order_id"]})["ticket"]
            s.outbox.items[key]["status"] = "held_for_review"
            if appr["decision"] == "timeout_deny":
                outcome = "denied"
                text += f" We couldn't complete the review in time; reference {ticket}."
            else:
                outcome = "queued_for_review"
                s.review_queue.append({"key": key, "reason": "approval SLA expired"})
                text += (
                    f" A specialist still needs to approve this; reference {ticket}. "
                    "No refund has been issued yet. You'll hear from us within 1 "
                    "business day."
                )
        else:
            if appr and appr["decision"] == "approve":
                text = text.replace(
                    "I've asked a care specialist to approve it.", "A care specialist approved it."
                )
            item = s.outbox.put(
                key,
                {
                    "order_id": state["order"]["order_id"],
                    "customer_id": req["customer_id"],
                    "amount": p["amount"],
                    "command": "issue_refund",
                },
            )
            if item["status"] == "held_for_review":
                item["status"] = "queued"
            ticket = item["ticket"]
            if dispatch(s, writer, item):
                outcome = "refund_issued"
                text += f" The payment provider confirmed refund {item['refund_id']}."
            else:
                outcome = "refund_queued"
                exits.append(exit_record("finalize", "degrade", "payments slow/down: queued"))
                text += (
                    f" Your refund request is queued with reference {ticket}; the payment "
                    "provider hasn't confirmed it yet. We'll email you as soon as it does."
                )
        return {
            "outcome": outcome,
            "reply": text,
            "ticket": ticket,
            "exits": exits,
            "trace": ["finalize"],
        }

    # ---------------------------------------------------------------- handoff
    def handoff(state: CareState) -> dict[str, Any]:
        route = state.get("route")
        req = state["request"]
        ref = "CS-" + req["request_id"].split("-")[-1]
        replies = {
            "fraud": (
                "handoff_specialist",
                f"Thanks for reaching out. A specialist team will look at this and "
                f"reply by email; your reference is {ref}.",
            ),
            "clarify": (
                "clarify",
                "I can help with that. Which order is it (e.g. O-1234), and what "
                "happened with the delivery?",
            ),
            "human": (
                "routed_to_agent",
                f"I've passed this to a care agent who can help; reference {ref}.",
            ),
            "not_found": (
                "order_not_found",
                "I couldn't find that order on your account. Could you check the order number?",
            ),
            "sor_down": (
                "escalated",
                f"I can't see your order details right now. I've opened case {ref} "
                "and a care agent will follow up; nothing has been changed yet.",
            ),
            "budget": (
                "escalated",
                f"I've passed this to a care agent to finish; reference {ref}.",
            ),
        }
        outcome, text = replies[route]
        if route in ("fraud", "human", "sor_down", "budget"):
            s.review_queue.append({"key": ref, "reason": route, "customer_id": req["customer_id"]})
        exits = []
        if route == "fraud":
            exits.append(exit_record("handoff", "escalate", "fraud pre-route: specialist team"))
        return {
            "outcome": outcome,
            "reply": text,
            "ticket": ref,
            "exits": exits,
            "trace": ["handoff"],
        }

    # ---------------------------------------------------------------- wiring
    g = StateGraph(CareState)
    g.add_node("classify", classify)
    g.add_node("plan", plan)
    g.add_node("order", order, destinations=("policy", "history", "refund", "handoff"))
    g.add_node("policy", policy)
    g.add_node("history", history)
    g.add_node("refund", refund)
    g.add_node("critic", critic, destinations=("human_approval", "finalize"))
    g.add_node("human_approval", human_approval)
    g.add_node("finalize", finalize)
    g.add_node("handoff", handoff)
    g.add_edge(START, "classify")
    g.add_conditional_edges(
        "classify", lambda st: "plan" if st["route"] == "plan" else "handoff", ["plan", "handoff"]
    )
    g.add_edge("plan", "order")
    g.add_edge("policy", "refund")
    g.add_edge("history", "refund")
    g.add_edge("refund", "critic")
    g.add_edge("human_approval", "finalize")
    g.add_edge("finalize", END)
    g.add_edge("handoff", END)
    return g.compile(checkpointer=checkpointer or MemorySaver(), name="care_e2e")


def sweep_expired(graph: Any, systems: Systems, now: datetime) -> list[str]:
    """SLA timer: resume every approval whose deadline passed with a timeout decision."""
    expired = [t for t, due in list(systems.pending_approvals.items()) if due <= now]
    for thread in expired:
        graph.invoke(Command(resume={"timeout": True}), {"configurable": {"thread_id": thread}})
    return expired
