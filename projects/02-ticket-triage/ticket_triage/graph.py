"""Router graph.

redact_pii -> classify -> validate --invalid (<=1)--> repair -> validate
                                   --invalid again--> human_review
                          valid --> confidence gate:
                              < 0.40 human_review | < 0.60 clarify | else intent queue handler

Doctrine wiring: the model is a fallback chain (all deployments down -> human queue, never a
guessed route); ticket text is PII-redacted *and* sanitised for injected instructions (a
suspected injection escalates to a human); routed tickets are created in the service desk
via the ticketing MCP server through a ToolGateway (idempotent on the inbound ticket id;
outage -> outbox for replay). Non-happy exits are appended to ``state["exits"]``.
"""

from __future__ import annotations

import operator
import re
from typing import Annotated, Any, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

from shared.context import looks_like_injection, sanitize
from shared.observability import install
from shared.resilience import ModelUnavailableError, exit_record, with_fallback
from shared.tools import SystemOfRecordUnavailableError
from ticket_triage import llm as prompts
from ticket_triage.pii import redact
from ticket_triage.schema import (
    CONFIDENCE_FLOOR,
    HUMAN_FLOOR,
    MAX_REPAIRS,
    QUEUES,
    SLA_HOURS,
    TicketClassification,
    TriageResult,
)
from ticket_triage.sor import TicketingBackend, build_gateway

ACKS = {
    "billing_queue": "Our billing team is reviewing the charge and will reply within {sla}h.",
    "tech_support_queue": "A support engineer is looking into the issue; expect an update "
    "within {sla}h.",
    "account_security_queue": "For your security, our account team will verify your identity "
    "before making changes. Expect a reply within {sla}h.",
    "product_feedback_queue": "Thanks for the suggestion! We've shared it with our product team.",
    "retention_queue": "We're sorry to see you consider leaving. An account specialist will "
    "reach out within {sla}h.",
}


class TriageState(TypedDict, total=False):
    ticket: dict[str, str]
    redacted: str
    redactions: dict[str, int]
    raw_output: str
    classification: dict[str, Any] | None
    validation_errors: str
    repair_attempts: int
    injection: bool
    model_down: bool
    result: dict[str, Any]
    trace: Annotated[list[str], operator.add]
    exits: Annotated[list[dict[str, str]], operator.add]


def _parse(raw: str) -> tuple[TicketClassification | None, str]:
    m = re.search(r"\{.*\}", raw, re.S)
    try:
        return TicketClassification.model_validate_json(m.group(0) if m else raw), ""
    except ValidationError as e:
        errs = "; ".join(
            f"{'.'.join(map(str, x['loc'])) or 'json'}: {x['msg']}" for x in e.errors()
        )
        return None, errs


def build_graph(
    llm: BaseChatModel | None = None,
    ticketing: TicketingBackend | None = None,
    outbox: list[dict[str, Any]] | None = None,
):
    install()
    if llm is None:
        from shared.llm import get_llm

        llm = get_llm(mock_responder=prompts.mock_responder)
    llm = with_fallback(llm)
    ticketing = ticketing if ticketing is not None else TicketingBackend()
    outbox = outbox if outbox is not None else []
    gw = build_gateway(ticketing)

    def open_ticket(state: TriageState, queue: str, priority: str, summary: str):
        """Create the ticket in the service desk; degrade to the outbox on outage."""
        args = {
            "queue": queue,
            "subject": state["redacted"].splitlines()[0][:120],
            "summary": summary,
            "priority": priority,
            "idempotency_key": f"triage:{state['ticket']['id']}",
        }
        try:
            created = gw.call("ticketing", "create_ticket", dry_run=False, **args)
            return created["ticket_id"], []
        except SystemOfRecordUnavailableError as exc:
            outbox.append({"system": "ticketing", **args})
            return None, [exit_record(queue, "degrade", f"ticketing unavailable, queued: {exc}")]

    def redact_pii(state: TriageState) -> dict[str, Any]:
        t = state["ticket"]
        text, _vault, counts = redact(f"Subject: {t['subject']}\n\n{t['body']}")
        # The vault stays in memory of this node only: never checkpointed, logged or prompted.
        injection = looks_like_injection(text)
        exits = []
        if injection:  # ticket text is untrusted data: neutralise, then route to a human
            text = sanitize(text, redact_pii=False).text
            exits = [exit_record("redact_pii", "escalate", "suspected prompt injection")]
        return {
            "redacted": text,
            "redactions": dict(counts),
            "repair_attempts": 0,
            "injection": injection,
            "model_down": False,
            "trace": ["redact_pii"],
            "exits": exits,
        }

    def classify(state: TriageState) -> dict[str, Any]:
        try:
            raw = llm.invoke(
                [SystemMessage(prompts.CLASSIFY_SYSTEM), HumanMessage(state["redacted"])]
            ).content
        except ModelUnavailableError:
            return {
                "raw_output": "",
                "model_down": True,
                "trace": ["classify"],
                "exits": [exit_record("classify", "degrade", "model unavailable: human queue")],
            }
        return {"raw_output": str(raw), "trace": ["classify"]}

    def validate(state: TriageState) -> dict[str, Any]:
        parsed, errors = _parse(state["raw_output"])
        return {
            "classification": parsed.model_dump() if parsed else None,
            "validation_errors": errors,
            "trace": ["validate"],
        }

    def repair(state: TriageState) -> dict[str, Any]:
        try:
            raw = _repair_call(state)
        except ModelUnavailableError:
            return {
                "model_down": True,
                "repair_attempts": state["repair_attempts"] + 1,
                "trace": ["repair"],
                "exits": [exit_record("repair", "degrade", "model unavailable: human queue")],
            }
        return {
            "raw_output": str(raw),
            "repair_attempts": state["repair_attempts"] + 1,
            "trace": ["repair"],
        }

    def _repair_call(state: TriageState) -> str:
        return llm.invoke(
            [
                SystemMessage(prompts.REPAIR_SYSTEM.format(errors=state["validation_errors"])),
                HumanMessage(state["redacted"]),
                AIMessage(state["raw_output"]),
                HumanMessage("Return the corrected JSON only."),
            ]
        ).content

    def route(state: TriageState) -> str:
        c = state["classification"]
        if state.get("injection") or state.get("model_down"):
            return "human_review"
        if c is None:
            return "repair" if state["repair_attempts"] < MAX_REPAIRS else "human_review"
        if c["confidence"] < HUMAN_FLOOR or c["intent"] == "other":
            return "human_review"
        if c["confidence"] < CONFIDENCE_FLOOR:
            return "clarify"
        return QUEUES[c["intent"]]

    def result(state: TriageState, **kw: Any) -> dict[str, Any]:
        c = state.get("classification")
        return TriageResult(
            ticket_id=state["ticket"]["id"],
            classification=TicketClassification(**c) if c else None,
            redactions=state["redactions"],
            repair_attempts=state["repair_attempts"],
            **kw,
        ).model_dump()

    def make_queue_handler(queue: str):
        def handler(state: TriageState) -> dict[str, Any]:
            c = state["classification"]
            sla = SLA_HOURS[c["urgency"]]
            ref, exits = open_ticket(state, queue, c["urgency"], c["summary"])
            return {
                "result": result(
                    state,
                    route="queue",
                    queue=queue,
                    sla_hours=sla,
                    page_on_call=c["urgency"] == "critical",
                    reason=f"{c['intent']} ({c['confidence']:.2f}) / {c['urgency']}",
                    customer_reply=ACKS[queue].format(sla=sla),
                    ticket_ref=ref,
                ),
                "trace": [queue],
                "exits": exits,
            }

        return handler

    def clarify(state: TriageState) -> dict[str, Any]:
        exits = []
        try:
            q = llm.invoke(
                [SystemMessage(prompts.CLARIFY_SYSTEM), HumanMessage(state["redacted"])]
            ).content
        except ModelUnavailableError:
            q = "Could you share a bit more detail - what were you trying to do, and what happened?"
            exits = [exit_record("clarify", "degrade", "model unavailable: template question")]
        c = state["classification"]
        return {
            "result": result(
                state,
                route="clarify",
                reason=f"confidence {c['confidence']:.2f} < {CONFIDENCE_FLOOR}",
                customer_reply=str(q),
            ),
            "trace": ["clarify"],
            "exits": exits,
        }

    def human_review(state: TriageState) -> dict[str, Any]:
        c = state.get("classification")
        if state.get("injection"):
            reason = "suspected prompt injection in ticket text"
        elif state.get("model_down"):
            reason = "classifier unavailable (all model deployments down)"
        elif c is None:
            reason = f"schema validation failed after repair: {state['validation_errors']}"
        elif c["intent"] == "other":
            reason = "intent 'other' has no automated queue"
        else:
            reason = f"confidence {c['confidence']:.2f} < {HUMAN_FLOOR}"
        priority = c["urgency"] if c else "medium"
        ref, exits = open_ticket(state, "triage_human_queue", priority, reason)
        return {
            "result": result(
                state,
                route="human_review",
                queue="triage_human_queue",
                reason=reason,
                customer_reply="Thanks! A member of our team will review your request shortly.",
                ticket_ref=ref,
            ),
            "trace": ["human_review"],
            "exits": exits,
        }

    g = StateGraph(TriageState)
    for name, fn in [
        ("redact_pii", redact_pii),
        ("classify", classify),
        ("validate", validate),
        ("repair", repair),
        ("clarify", clarify),
        ("human_review", human_review),
    ]:
        g.add_node(name, fn)
    for queue in QUEUES.values():
        g.add_node(queue, make_queue_handler(queue))
    g.add_edge(START, "redact_pii")
    g.add_edge("redact_pii", "classify")
    g.add_edge("classify", "validate")
    g.add_edge("repair", "validate")
    g.add_conditional_edges(
        "validate", route, ["repair", "clarify", "human_review", *QUEUES.values()]
    )
    for terminal in ["clarify", "human_review", *QUEUES.values()]:
        g.add_edge(terminal, END)
    compiled = g.compile(name="ticket-triage")
    compiled.gateway, compiled.ticketing, compiled.outbox = gw, ticketing, outbox
    return compiled
