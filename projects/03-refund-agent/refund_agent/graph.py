"""Refund workflow as a deterministic LangGraph StateGraph with a HITL interrupt.

classify_intent -> verify_identity -> check_order -> check_refund_policy -> decide
    decide: fraud -> fraud_review | ineligible -> deny | < $50 -> issue_refund
            | >= $50 -> human_approval (interrupt) -> issue_refund | notify_rejection
identity failure -> escalate. Every terminal node -> compose_reply -> END.

Doctrine wiring: OMS / CRM / payments are MCP servers reached through a ToolGateway with the
agent's identity + allowlist; policy text comes from the shared context builder as-of the
delivery date (ACL + temporal); the model is a fallback chain; every non-happy exit a node
takes is appended to ``state["exits"]`` (see doctrine.yaml five-exit table).
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from refund_agent import llm as llm_ops
from refund_agent.knowledge import builder as policy_builder
from refund_agent.knowledge import policy_citations
from refund_agent.policy import AUTO_APPROVE_LIMIT, check_eligibility, cite, fraud_flags
from refund_agent.services import Services, seed_services
from refund_agent.sor import OrderNotFoundError, build_gateway
from refund_agent.state import FinalReply, RefundState
from shared.context import RetrievalError, looks_like_injection
from shared.observability import install
from shared.resilience import Backoff, exit_record, with_fallback
from shared.tools import SystemOfRecordUnavailableError


def build_graph(
    services: Services | None = None,
    llm: BaseChatModel | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
):
    """Compile the refund graph. Dependencies are injected so tests use fakes."""
    services = services or seed_services()
    install()  # OpenTelemetry spans for graph / nodes / model / tools
    if llm is None:
        from shared.llm import get_llm

        llm = get_llm(mock_responder=llm_ops.mock_responder)
    llm = with_fallback(llm)  # primary -> fallback deployment -> degrade
    checkpointer = checkpointer or MemorySaver()
    audit = services.audit
    gw = build_gateway(services)
    payments_gw = gw.scoped(
        gw.agent, gw.identity, {"payments.issue_refund"}, quotas={"payments.issue_refund": 3}
    )
    payments_gw.retry = Backoff(attempts=3, base_s=0.2)
    policy_kb = policy_builder()

    def get_order(order_id: str) -> dict[str, Any] | None:
        try:
            return gw.call("oms", "get_order", order_id=order_id)
        except OrderNotFoundError:
            return None

    def crm_note(customer_id: str, note: str, key: str) -> bool:
        """CRM follow-ups never block the customer outcome: queue on outage (degrade)."""
        try:
            gw.call(
                "crm",
                "add_case_note",
                customer_id=customer_id,
                note=note,
                idempotency_key=key,
                dry_run=False,
            )
            return True
        except SystemOfRecordUnavailableError:
            services.outbox.append(
                {"system": "crm", "customer_id": customer_id, "note": note, "idempotency_key": key}
            )
            return False

    def rid(state: RefundState) -> str:
        return state["request"]["request_id"]

    # ---- nodes -----------------------------------------------------------------
    def classify_intent(state: RefundState) -> dict[str, Any]:
        message = state["request"]["message"]
        injected = looks_like_injection(message)
        intent, degraded = llm_ops.classify_intent_ex(llm, message)
        audit.record(rid(state), "intent_classified", intent=intent, degraded=degraded)
        exits = (
            [exit_record("classify_intent", "degrade", "model unavailable: keyword classifier")]
            if degraded
            else []
        )
        return {
            "intent": intent,
            "injection_detected": injected,
            "exits": exits,
            "trace": ["classify_intent"],
        }

    def verify_identity(state: RefundState) -> dict[str, Any]:
        req = state["request"]
        try:
            ok = gw.call(
                "crm", "verify_customer", customer_id=req["customer_id"], email=req["email"]
            )["verified"]
            order = get_order(req["order_id"])
        except SystemOfRecordUnavailableError as exc:
            # Never guess identity or ownership: hand to a human with an honest reason.
            reason = "Order/customer systems unavailable; cannot verify right now."
            audit.record(rid(state), "identity_checked", verified=False, reason=reason)
            return {
                "identity_verified": False,
                "identity_reason": reason,
                "citations": [cite("RP-1")],
                "trace": ["verify_identity"],
                "exits": [exit_record("verify_identity", "escalate", str(exc))],
            }
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
        try:
            order = get_order(state["request"]["order_id"])
        except SystemOfRecordUnavailableError as exc:
            audit.record(rid(state), "order_unavailable", error=str(exc))
            return {
                "order": None,
                "amount": 0.0,
                "identity_verified": False,
                "identity_reason": "Order system unavailable.",
                "trace": ["check_order"],
                "exits": [exit_record("check_order", "escalate", str(exc))],
            }
        audit.record(rid(state), "order_loaded", found=order is not None)
        return {
            "order": order,
            "amount": order["amount"] if order else 0.0,
            "trace": ["check_order"],
        }

    def check_refund_policy(state: RefundState) -> dict[str, Any]:
        eligible, reason, citation = check_eligibility(state["order"], services.today)
        flags = fraud_flags(state["request"]["message"])
        rules = [citation.split(":")[0]] if citation else []
        exits = []
        if flags:
            route = "fraud_review"
            rules.append("RP-7")
        elif not eligible:
            route = "deny"
        elif state.get("injection_detected"):
            # Injected instructions in customer text: never auto-pay; a human decides.
            route = "human_approval"
            rules.append("RP-6")
            exits.append(
                exit_record(
                    "check_refund_policy", "escalate", "prompt injection in customer message"
                )
            )
        elif state["amount"] < AUTO_APPROVE_LIMIT:
            route = "auto_refund"
            rules.append("RP-5")
        else:
            route = "human_approval"
            rules.append("RP-6")
        # Temporal policy RAG: the policy in force on the delivery date is what we cite.
        as_of = state["order"]["delivered_on"] if state.get("order") else services.today
        try:
            citations, missing = policy_citations(policy_kb, rules, as_of)
            source = "retrieval"
        except RetrievalError:
            citations, missing = [], rules
            source = "cache"
        if missing:
            # Known-policy cache keeps the answer true, but evidence-dependent autonomous
            # writes are disabled: an auto refund becomes a human approval.
            citations += [cite(r) for r in missing]
            source = "cache"
            if route == "auto_refund":
                route = "human_approval"
                citations.append(cite("RP-6"))
            exits.append(
                exit_record(
                    "check_refund_policy",
                    "degrade",
                    f"policy evidence unavailable for {missing}; cached policy, autonomy disabled",
                )
            )
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
            "policy_source": source,
            "exits": exits,
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
        key = f"refund:{req['order_id']}"
        try:
            refund = payments_gw.call(
                "payments",
                "issue_refund",
                order_id=req["order_id"],
                amount=state["amount"],
                idempotency_key=key,
                dry_run=False,
            )
        except SystemOfRecordUnavailableError as exc:
            # Payment provider down after retries: queue with the same idempotency key and
            # tell the customer the truth (queued, not paid).
            services.outbox.append(
                {
                    "system": "payments",
                    "order_id": req["order_id"],
                    "amount": state["amount"],
                    "idempotency_key": key,
                }
            )
            audit.record(rid(state), "refund_queued", error=str(exc))
            return {
                "outcome": "refund_queued",
                "trace": ["issue_refund"],
                "exits": [
                    exit_record(
                        "issue_refund", "degrade", "payment provider unavailable: refund queued"
                    )
                ],
            }
        exits = []
        if refund.get("replayed"):
            exits.append(
                exit_record(
                    "issue_refund", "retry", "replayed from checkpoint; provider deduped the key"
                )
            )
        try:
            gw.call(
                "oms",
                "mark_order_refunded",
                order_id=req["order_id"],
                refund_id=refund["refund_id"],
                idempotency_key=f"oms:{key}",
                dry_run=False,
            )
        except SystemOfRecordUnavailableError:
            services.outbox.append(
                {"system": "oms", "order_id": req["order_id"], "refund_id": refund["refund_id"]}
            )
            exits.append(exit_record("issue_refund", "degrade", "OMS flag queued"))
        audit.record(rid(state), "refund_issued", **refund)
        note = f"Refund {refund['refund_id']} ${refund['amount']:.2f} issued."
        try:
            gw.call(
                "crm",
                "add_case_note",
                customer_id=req["customer_id"],
                note=note,
                idempotency_key=f"crm:{key}",
                dry_run=False,
            )
        except SystemOfRecordUnavailableError:
            if not refund.get("replayed"):
                # First failure after money moved: crash to the checkpoint; the worker
                # replays this node and the provider dedupes the refund (retry exit).
                raise
            services.outbox.append(
                {
                    "system": "crm",
                    "customer_id": req["customer_id"],
                    "note": note,
                    "idempotency_key": f"crm:{key}",
                }
            )
            exits.append(exit_record("issue_refund", "degrade", "CRM note queued"))
        return {
            "refund": refund,
            "outcome": "refund_issued",
            "trace": ["issue_refund"],
            "exits": exits,
        }

    def notify_rejection(state: RefundState) -> dict[str, Any]:
        req = state["request"]
        ok = crm_note(
            req["customer_id"],
            f"Refund for {req['order_id']} rejected.",
            f"crm:reject:{req['order_id']}",
        )
        audit.record(rid(state), "refund_rejected")
        return {
            "outcome": "refund_rejected_by_reviewer",
            "trace": ["notify_rejection"],
            "exits": [] if ok else [exit_record("notify_rejection", "degrade", "CRM note queued")],
        }

    def deny(state: RefundState) -> dict[str, Any]:
        audit.record(rid(state), "refund_denied", reason=state["eligibility_reason"])
        return {"outcome": "refund_denied", "trace": ["deny"]}

    def fraud_review(state: RefundState) -> dict[str, Any]:
        req = state["request"]
        ok = crm_note(
            req["customer_id"],
            "Refund request sent to fraud review.",
            f"crm:fraud:{req['order_id']}",
        )
        audit.record(rid(state), "fraud_review_opened", flags=state["fraud_flags"])
        return {
            "outcome": "fraud_review",
            "trace": ["fraud_review"],
            "exits": [] if ok else [exit_record("fraud_review", "degrade", "CRM note queued")],
        }

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
            "reference": f"refund:{req['order_id']}",
        }
        reply, degraded = llm_ops.write_reply_ex(llm, facts)
        final = FinalReply(
            intent=state.get("intent", "other"),
            citations=list(dict.fromkeys(state.get("citations", []))),
            next_action=state["outcome"],
            customer_safe_reply=reply,
        )
        audit.record(rid(state), "reply_composed", next_action=final.next_action)
        exits = (
            [exit_record("compose_reply", "degrade", "model unavailable: template reply")]
            if degraded
            else []
        )
        return {"final": final.model_dump(), "trace": ["compose_reply"], "exits": exits}

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
    graph = g.compile(checkpointer=checkpointer, name="refund-agent")
    graph.gateway = gw  # exposed for tests / evals (call log, stats)
    return graph
