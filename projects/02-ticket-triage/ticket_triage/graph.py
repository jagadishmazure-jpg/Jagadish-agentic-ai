"""Router graph.

redact_pii -> classify -> validate --invalid (<=1)--> repair -> validate
                                   --invalid again--> human_review
                          valid --> confidence gate:
                              < 0.40 human_review | < 0.60 clarify | else intent queue handler
"""

from __future__ import annotations

import operator
import re
from typing import Annotated, Any, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import ValidationError

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
    result: dict[str, Any]
    trace: Annotated[list[str], operator.add]


def _parse(raw: str) -> tuple[TicketClassification | None, str]:
    m = re.search(r"\{.*\}", raw, re.S)
    try:
        return TicketClassification.model_validate_json(m.group(0) if m else raw), ""
    except ValidationError as e:
        errs = "; ".join(
            f"{'.'.join(map(str, x['loc'])) or 'json'}: {x['msg']}" for x in e.errors()
        )
        return None, errs


def build_graph(llm: BaseChatModel | None = None):
    if llm is None:
        from shared.llm import get_llm

        llm = get_llm(mock_responder=prompts.mock_responder)

    def redact_pii(state: TriageState) -> dict[str, Any]:
        t = state["ticket"]
        text, _vault, counts = redact(f"Subject: {t['subject']}\n\n{t['body']}")
        # The vault stays in memory of this node only: never checkpointed, logged or prompted.
        return {
            "redacted": text,
            "redactions": dict(counts),
            "repair_attempts": 0,
            "trace": ["redact_pii"],
        }

    def classify(state: TriageState) -> dict[str, Any]:
        raw = llm.invoke(
            [SystemMessage(prompts.CLASSIFY_SYSTEM), HumanMessage(state["redacted"])]
        ).content
        return {"raw_output": str(raw), "trace": ["classify"]}

    def validate(state: TriageState) -> dict[str, Any]:
        parsed, errors = _parse(state["raw_output"])
        return {
            "classification": parsed.model_dump() if parsed else None,
            "validation_errors": errors,
            "trace": ["validate"],
        }

    def repair(state: TriageState) -> dict[str, Any]:
        raw = llm.invoke(
            [
                SystemMessage(prompts.REPAIR_SYSTEM.format(errors=state["validation_errors"])),
                HumanMessage(state["redacted"]),
                AIMessage(state["raw_output"]),
                HumanMessage("Return the corrected JSON only."),
            ]
        ).content
        return {
            "raw_output": str(raw),
            "repair_attempts": state["repair_attempts"] + 1,
            "trace": ["repair"],
        }

    def route(state: TriageState) -> str:
        c = state["classification"]
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
            return {
                "result": result(
                    state,
                    route="queue",
                    queue=queue,
                    sla_hours=sla,
                    page_on_call=c["urgency"] == "critical",
                    reason=f"{c['intent']} ({c['confidence']:.2f}) / {c['urgency']}",
                    customer_reply=ACKS[queue].format(sla=sla),
                ),
                "trace": [queue],
            }

        return handler

    def clarify(state: TriageState) -> dict[str, Any]:
        q = llm.invoke(
            [SystemMessage(prompts.CLARIFY_SYSTEM), HumanMessage(state["redacted"])]
        ).content
        c = state["classification"]
        return {
            "result": result(
                state,
                route="clarify",
                reason=f"confidence {c['confidence']:.2f} < {CONFIDENCE_FLOOR}",
                customer_reply=str(q),
            ),
            "trace": ["clarify"],
        }

    def human_review(state: TriageState) -> dict[str, Any]:
        c = state.get("classification")
        if c is None:
            reason = f"schema validation failed after repair: {state['validation_errors']}"
        elif c["intent"] == "other":
            reason = "intent 'other' has no automated queue"
        else:
            reason = f"confidence {c['confidence']:.2f} < {HUMAN_FLOOR}"
        return {
            "result": result(
                state,
                route="human_review",
                queue="triage_human_queue",
                reason=reason,
                customer_reply="Thanks! A member of our team will review your request shortly.",
            ),
            "trace": ["human_review"],
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
    return g.compile()
