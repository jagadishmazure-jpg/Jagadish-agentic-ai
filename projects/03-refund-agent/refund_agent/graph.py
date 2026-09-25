"""Refund workflow as a deterministic LangGraph StateGraph with a HITL interrupt.

classify_intent -> verify_identity -> check_order -> check_refund_policy -> decide
    decide: fraud -> fraud_review | ineligible -> deny | < $50 -> issue_refund
            | >= $50 -> human_approval (interrupt) -> issue_refund | notify_rejection
identity failure -> escalate. Every terminal node -> compose_reply -> END.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from refund_agent import llm as llm_ops
from refund_agent.policy import AUTO_APPROVE_LIMIT, check_eligibility, cite, fraud_flags
from refund_agent.services import Services
from refund_agent.state import FinalReply, RefundState


def build_graph(
    services: Services,
    llm: BaseChatModel | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
):
    """Compile the refund graph. Dependencies are injected so tests use fakes."""
    if llm is None:
        from shared.llm import get_llm

        llm = get_llm(mock_responder=llm_ops.mock_responder)
    checkpointer = checkpointer or MemorySaver()
    audit = services.audit

    def rid(state: RefundState) -> str:
        return state["request"]["request_id"]

    # ---- nodes -----------------------------------------------------------------
    def classify_intent(state: RefundState) -> dict[str, Any]:
        intent = llm_ops.classify_intent(llm, state["request"]["message"])
        audit.record(rid(state), "intent_classified", intent=intent)
        return {"intent": intent, "trace": ["classify_intent"]}

    def verify_identity(state: RefundState) -> dict[str, Any]:
        req = state["request"]
        ok = services.customers.verify(req["customer_id"], req["email"])
        order = services.orders.get(req["order_id"])
        if ok and order and order["customer_id"] != req["customer_id"]:
            ok, reason = False, "Order does not belong to this customer."
        else:
            reason = "verified" if ok else "Customer id / email mismatch."
        audit.record(rid(state), "identity_checked", verified=ok, reason=reason)
        return {
            "identity_verified": ok,
            "identity_reason": reason,
            "citations": [cite("RP-1")],
            "trace": ["verify_identity"],
        }

    def check_order(state: RefundState) -> dict[str, Any]:
        order = services.orders.get(state["request"]["order_id"])
        audit.record(rid(state), "order_loaded", found=order is not None)
        return {
            "order": order,
            "amount": order["amount"] if order else 0.0,
            "trace": ["check_order"],
        }

    def check_refund_policy(state: RefundState) -> dict[str, Any]:
        eligible, reason, citation = check_eligibility(state["order"], services.today)
        flags = fraud_flags(state["request"]["message"])
        citations = [citation] if citation else []
        if flags:
            route = "fraud_review"
            citations.append(cite("RP-7"))
        elif not eligible:
            route = "deny"
        elif state["amount"] < AUTO_APPROVE_LIMIT:
            route = "auto_refund"
            citations.append(cite("RP-5"))
        else:
            route = "human_approval"
            citations.append(cite("RP-6"))
        audit.record(
            rid(state),
            "policy_decision",
            route=route,
            eligible=eligible,
            reason=reason,
            fraud_flags=flags,
            amount=state["amount"],
        )
        if route == "human_approval":
            # Logged here, not in human_approval: that node re-runs on resume.
            audit.record(rid(state), "approval_requested", amount=state["amount"])
        return {
            "eligible": eligible,
            "eligibility_reason": reason,
            "fraud_flags": flags,
            "route": route,
            "citations": citations,
            "trace": ["check_refund_policy"],
        }

    def human_approval(state: RefundState) -> dict[str, Any]:
        # Pauses the graph; state is persisted by the checkpointer. On resume,
        # interrupt() returns the value passed via Command(resume=...).
        decision = interrupt(
            {
                "type": "refund_approval",
                "request_id": rid(state),
                "order_id": state["request"]["order_id"],
                "amount": state["amount"],
                "reason": state["eligibility_reason"],
                "customer_message": state["request"]["message"],
            }
        )
        if isinstance(decision, bool):
            decision = {"approved": decision}
        approval = {
            "approved": bool(decision.get("approved")),
            "reviewer": decision.get("reviewer", "unknown"),
            "note": decision.get("note", ""),
        }
        audit.record(rid(state), "approval_decision", **approval)
        return {"approval": approval, "trace": ["human_approval"]}

    def issue_refund(state: RefundState) -> dict[str, Any]:
        req = state["request"]
        # Full refunds only (RP-3), so the order id is a natural idempotency key:
        # retries, replays and duplicate submissions can never move money twice.
        refund = services.refunds.issue(
            idempotency_key=f"refund:{req['order_id']}",
            order_id=req["order_id"],
            amount=state["amount"],
        )
        services.orders.mark_refunded(req["order_id"], refund["refund_id"])
        audit.record(rid(state), "refund_issued", **refund)
        services.crm.add_note(
            req["customer_id"], f"Refund {refund['refund_id']} ${refund['amount']:.2f} issued."
        )
        return {"refund": refund, "outcome": "refund_issued", "trace": ["issue_refund"]}

    def notify_rejection(state: RefundState) -> dict[str, Any]:
        req = state["request"]
        services.crm.add_note(req["customer_id"], f"Refund for {req['order_id']} rejected.")
        audit.record(rid(state), "refund_rejected")
        return {"outcome": "refund_rejected_by_reviewer", "trace": ["notify_rejection"]}

    def deny(state: RefundState) -> dict[str, Any]:
        audit.record(rid(state), "refund_denied", reason=state["eligibility_reason"])
        return {"outcome": "refund_denied", "trace": ["deny"]}

    def fraud_review(state: RefundState) -> dict[str, Any]:
        req = state["request"]
        services.crm.add_note(req["customer_id"], "Refund request sent to fraud review.")
        audit.record(rid(state), "fraud_review_opened", flags=state["fraud_flags"])
        return {"outcome": "fraud_review", "trace": ["fraud_review"]}

    def escalate(state: RefundState) -> dict[str, Any]:
        audit.record(rid(state), "escalated", reason=state["identity_reason"])
        return {"outcome": "escalated_to_agent", "trace": ["escalate"]}

    def compose_reply(state: RefundState) -> dict[str, Any]:
        req = state["request"]
        refund = state.get("refund") or {}
        facts = {
            "next_action": state["outcome"],
            "order_id": req["order_id"],
            "amount": refund.get("amount", state.get("amount", 0.0)),
            "refund_id": refund.get("refund_id", ""),
            "reason": state.get("eligibility_reason", ""),
        }
        final = FinalReply(
            intent=state.get("intent", "other"),
            citations=list(dict.fromkeys(state.get("citations", []))),
            next_action=state["outcome"],
            customer_safe_reply=llm_ops.write_reply(llm, facts),
        )
        audit.record(rid(state), "reply_composed", next_action=final.next_action)
        return {"final": final.model_dump(), "trace": ["compose_reply"]}

    # ---- routing (pure functions of state) --------------------------------------
    def after_identity(state: RefundState) -> str:
        return "check_order" if state["identity_verified"] else "escalate"

    def decide(state: RefundState) -> str:
        return {
            "fraud_review": "fraud_review",
            "deny": "deny",
            "auto_refund": "issue_refund",
            "human_approval": "human_approval",
        }[state["route"]]

    def after_approval(state: RefundState) -> str:
        return "issue_refund" if state["approval"]["approved"] else "notify_rejection"

    # ---- wiring -----------------------------------------------------------------
    g = StateGraph(RefundState)
    for fn in (
        classify_intent,
        verify_identity,
        check_order,
        check_refund_policy,
        human_approval,
        issue_refund,
        notify_rejection,
        deny,
        fraud_review,
        escalate,
        compose_reply,
    ):
        g.add_node(fn.__name__, fn)

    g.add_edge(START, "classify_intent")
    g.add_edge("classify_intent", "verify_identity")
    g.add_conditional_edges("verify_identity", after_identity, ["check_order", "escalate"])
    g.add_edge("check_order", "check_refund_policy")
    g.add_conditional_edges(
        "check_refund_policy", decide, ["fraud_review", "deny", "issue_refund", "human_approval"]
    )
    g.add_conditional_edges("human_approval", after_approval, ["issue_refund", "notify_rejection"])
    for terminal in ("issue_refund", "notify_rejection", "deny", "fraud_review", "escalate"):
        g.add_edge(terminal, "compose_reply")
    g.add_edge("compose_reply", END)
    return g.compile(checkpointer=checkpointer)
