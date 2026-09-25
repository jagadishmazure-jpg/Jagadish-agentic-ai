"""Governed collections workflow.

load_account (collections-reader) -> policy_gate
    hardship   -> hardship_referral
    no_contact -> no_contact            (cease-and-desist / dispute)
    defer      -> defer                 (outside hours / frequency cap)
    allowed    -> propose_plan (plan-proposer; LLM + plan policy + message guard)
               -> reviewer_approval (interrupt, separation of duties)
                    approve -> execute_plan (plan-writer) -> send_outreach (outreach-sender,
                               contact rules re-checked at send time)
                    reject  -> rejected
every branch -> finalize (verify hash-chained audit log)

Doctrine wiring: every tool call crosses MCP through a per-identity ToolGateway (see sor.py);
the model is a fallback chain (all deployments down -> policy-default plan + safe template,
still human-reviewed); CRM outage at load -> deferred to the next run (never contact on stale
data); payments outage after approval -> plan write queued for replay and no outreach sent;
messaging outage -> message deferred. Non-happy exits go to ``state["exits"]``.
"""

from __future__ import annotations

import json
import operator
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from collections_agent import policy
from collections_agent.audit import mask
from collections_agent.llm import DRAFT_SYSTEM, PROPOSE_SYSTEM, mock_responder
from collections_agent.registry import IDENTITIES
from collections_agent.systems import Systems, seed_systems
from shared.llm import get_llm
from shared.observability import install
from shared.resilience import ModelUnavailableError, exit_record, with_fallback
from shared.tools import SystemOfRecordUnavailableError

NEUTRALISED = "[removed: suspected injected instruction]"


class CollectionsState(TypedDict, total=False):
    account_id: str
    account: dict[str, Any]
    history: list[dict[str, Any]]
    decision: str
    reasons: list[str]
    plan: dict[str, Any]
    plan_violations: list[str]
    rationale: str
    message: str
    message_issues: list[str]
    review: dict[str, Any]
    plan_record: dict[str, Any]
    message_record: dict[str, Any]
    next_allowed: str
    outcome: str
    audit_ok: bool
    unavailable: str
    exits: Annotated[list[dict[str, str]], operator.add]


def _parse_json(text: str) -> dict[str, Any]:
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        return json.loads(text[start:end])
    except ValueError:
        return {}


def build_graph(
    systems: Systems | None = None,
    llm: BaseChatModel | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
):
    s = systems or seed_systems()
    assert s.registry is not None
    install()
    llm = with_fallback(llm or get_llm(mock_responder=mock_responder))
    reader = s.registry.client("collections-reader")
    proposer = s.registry.client("plan-proposer")
    writer = s.registry.client("plan-writer")
    sender = s.registry.client("outreach-sender")

    def log(action: str, actor: str = "agent", **details: Any) -> None:
        s.audit.record(actor, action, s.clock(), **details)

    def load_account(state: CollectionsState) -> dict:
        try:
            acct = reader.call("get_account", account_id=state["account_id"])
            hist = reader.call("get_contact_history", account_id=state["account_id"])
        except SystemOfRecordUnavailableError as exc:
            log("load_failed", account_id=state["account_id"], error=str(exc))
            return {
                "unavailable": str(exc),
                "exits": [exit_record("load_account", "retry", "CRM unavailable: next run")],
            }
        exits = []
        if NEUTRALISED in json.dumps(acct):
            exits.append(exit_record("load_account", "degrade", "injected text neutralised"))
        return {"account": acct, "history": hist, "exits": exits}

    def policy_gate(state: CollectionsState) -> dict:
        if state.get("unavailable"):
            reasons = [f"systems unavailable - retry next run ({state['unavailable']})"]
            log(
                "policy_decision", account_id=state["account_id"], decision="defer", reasons=reasons
            )
            return {"decision": "defer", "reasons": reasons}
        decision, reasons = policy.contact_decision(state["account"], state["history"], s.now)
        log("policy_decision", account_id=state["account_id"], decision=decision, reasons=reasons)
        return {"decision": decision, "reasons": reasons}

    def hardship_referral(state: CollectionsState) -> dict:
        log("hardship_referral", account_id=state["account_id"], queue="hardship-team")
        return {"outcome": "hardship_referral"}

    def no_contact(state: CollectionsState) -> dict:
        log("contact_suppressed", account_id=state["account_id"], reasons=state["reasons"])
        return {"outcome": "no_contact"}

    def defer(state: CollectionsState) -> dict:
        if state.get("unavailable"):
            log("contact_deferred", account_id=state["account_id"], next_allowed="next run")
            return {"outcome": "deferred", "next_allowed": "next batch run"}
        nxt = policy.next_allowed_time(state["account"], s.now)
        log("contact_deferred", account_id=state["account_id"], next_allowed=nxt)
        return {"outcome": "deferred", "next_allowed": nxt}

    def propose_plan(state: CollectionsState) -> dict:
        acct = state["account"]
        # The LLM only sees a minimised, PII-free view of the account.
        view = {
            "balance": acct["balance"],
            "days_past_due": acct["days_past_due"],
            "limits": {
                "max_months": policy.MAX_MONTHS,
                "min_installment": policy.MIN_INSTALLMENT,
                "max_discount_pct": policy.MAX_DISCOUNT_PCT,
            },
        }
        exits = []
        try:
            raw = _parse_json(
                str(
                    llm.invoke(
                        [SystemMessage(PROPOSE_SYSTEM), HumanMessage(json.dumps(view))]
                    ).content
                )
            )
        except ModelUnavailableError:
            raw = {"rationale": "model unavailable: policy-default plan"}
            exits.append(exit_record("propose_plan", "degrade", "model unavailable: default plan"))
        terms, violations = policy.check_plan(raw, acct["balance"])
        try:
            plan = proposer.call("quote_plan", account_id=acct["account_id"], **terms)
        except SystemOfRecordUnavailableError as exc:
            return {
                "unavailable": str(exc),
                "exits": [*exits, exit_record("propose_plan", "retry", "ledger down: next run")],
            }
        first = acct["name"].split()[0]
        try:
            body = str(
                llm.invoke(
                    [
                        SystemMessage(DRAFT_SYSTEM),
                        HumanMessage(json.dumps({"first_name": first, "plan": plan})),
                    ]
                ).content
            ).strip()
        except ModelUnavailableError:
            body = ""  # -> message guard swaps in the safe template
        issues = policy.check_message(body)
        if issues:
            body = policy.safe_template(first, plan)
        log(
            "plan_proposed",
            account_id=acct["account_id"],
            plan=plan,
            llm_violations_clamped=violations,
            message_issues_replaced=issues,
        )
        return {
            "plan": plan,
            "plan_violations": violations,
            "message": body,
            "message_issues": issues,
            "rationale": raw.get("rationale", ""),
            "exits": exits,
        }

    def reviewer_approval(state: CollectionsState) -> dict:
        acct = state["account"]
        request = {
            "account": mask(
                {k: acct[k] for k in ("account_id", "name", "email", "balance", "days_past_due")}
            ),
            "plan": state["plan"],
            "policy_violations_clamped": state["plan_violations"],
            "message_issues_replaced": state["message_issues"],
            "draft_message": state["message"],
            "rationale": state.get("rationale", ""),
            "options": ["approve", "reject"],
        }
        review = interrupt(request)
        reviewer = str(review.get("reviewer", ""))
        decision = review.get("decision")
        if not reviewer or reviewer in IDENTITIES or reviewer.startswith("agent"):
            decision = "reject"  # separation of duties: agents cannot approve their own work
            review = {**review, "note": "invalid reviewer identity - auto-rejected"}
        log(
            "review_decision",
            actor=f"human:{reviewer or 'unknown'}",
            account_id=acct["account_id"],
            decision=decision,
            note=review.get("note", ""),
        )
        return {"review": {**review, "decision": decision}}

    def execute_plan(state: CollectionsState) -> dict:
        args = {
            "account_id": state["account_id"],
            "plan": state["plan"],
            "approved_by": state["review"]["reviewer"],
            "idempotency_key": f"{state['account_id']}:{state['plan']['total']}:"
            f"{state['plan']['months']}",
        }
        try:
            rec = writer.call("create_payment_plan", **args)
        except SystemOfRecordUnavailableError as exc:
            s.pending.append({"tool": "create_payment_plan", **args})
            log("plan_write_queued", account_id=state["account_id"], error=str(exc))
            return {
                "outcome": "plan_write_queued",
                "exits": [exit_record("execute_plan", "degrade", "payments down: write queued")],
            }
        return {"plan_record": rec}

    def send_outreach(state: CollectionsState) -> dict:
        # Time passes while a human reviews: contact rules are re-checked at send time.
        hist = reader.call("get_contact_history", account_id=state["account_id"])
        decision, reasons = policy.contact_decision(state["account"], hist, s.now)
        if decision != "allowed":
            nxt = policy.next_allowed_time(state["account"], s.now)
            log(
                "outreach_deferred",
                account_id=state["account_id"],
                reasons=reasons,
                next_allowed=nxt,
            )
            return {"outcome": "plan_created_message_deferred", "next_allowed": nxt}
        try:
            msg = sender.call(
                "send_message",
                account_id=state["account_id"],
                channel=state["account"]["channel"],
                body=state["message"],
            )
        except SystemOfRecordUnavailableError as exc:
            log("outreach_deferred", account_id=state["account_id"], reasons=[str(exc)])
            return {
                "outcome": "plan_created_message_deferred",
                "next_allowed": "when messaging recovers",
                "exits": [exit_record("send_outreach", "degrade", "messaging down: deferred")],
            }
        return {"message_record": msg, "outcome": "plan_created_message_sent"}

    def rejected(state: CollectionsState) -> dict:
        return {"outcome": "rejected"}

    def finalize(state: CollectionsState) -> dict:
        ok, _ = s.audit.verify()
        return {"audit_ok": ok}

    def route_policy(state: CollectionsState) -> str:
        return {
            "allowed": "propose_plan",
            "hardship": "hardship_referral",
            "no_contact": "no_contact",
        }.get(state["decision"], "defer")

    def route_review(state: CollectionsState) -> Literal["execute_plan", "rejected"]:
        return "execute_plan" if state["review"]["decision"] == "approve" else "rejected"

    g = StateGraph(CollectionsState)
    for name, fn in [
        ("load_account", load_account),
        ("policy_gate", policy_gate),
        ("hardship_referral", hardship_referral),
        ("no_contact", no_contact),
        ("defer", defer),
        ("propose_plan", propose_plan),
        ("reviewer_approval", reviewer_approval),
        ("execute_plan", execute_plan),
        ("send_outreach", send_outreach),
        ("rejected", rejected),
        ("finalize", finalize),
    ]:
        g.add_node(name, fn)
    g.add_edge(START, "load_account")
    g.add_edge("load_account", "policy_gate")
    g.add_conditional_edges(
        "policy_gate", route_policy, ["propose_plan", "hardship_referral", "no_contact", "defer"]
    )
    g.add_conditional_edges(
        "propose_plan",
        lambda st: "defer" if st.get("unavailable") else "reviewer_approval",
        ["reviewer_approval", "defer"],
    )
    g.add_conditional_edges("reviewer_approval", route_review, ["execute_plan", "rejected"])
    g.add_conditional_edges(
        "execute_plan",
        lambda st: "send_outreach" if st.get("plan_record") else "finalize",
        ["send_outreach", "finalize"],
    )
    for n in ("hardship_referral", "no_contact", "defer", "send_outreach", "rejected"):
        g.add_edge(n, "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer or MemorySaver(), name="collections-agent")
