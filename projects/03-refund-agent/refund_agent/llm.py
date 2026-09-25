"""The only two places the LLM is used: intent classification and reply writing.

Both have deterministic guards so a misbehaving model can't change control flow
or leak internal details. The mock responder mirrors what a real model would do.
"""

from __future__ import annotations

import json
from collections.abc import Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from refund_agent.state import Intent
from shared.resilience import ModelUnavailableError

INTENTS: tuple[Intent, ...] = ("refund_request", "order_status", "complaint", "other")

CLASSIFY_SYSTEM = (
    "TASK: CLASSIFY_INTENT\n"
    "Classify the customer's message into exactly one label: "
    + ", ".join(INTENTS)
    + ". Reply with the label only."
)

REPLY_SYSTEM = (
    "TASK: WRITE_REPLY\n"
    "You write short, polite customer-support replies (max 3 sentences). Use ONLY the facts "
    "in the JSON. Never mention internal policy IDs, fraud scoring, reviewers or systems. "
    "Never promise anything not stated in the facts."
)

MAX_REPLY_CHARS = 600
_FORBIDDEN_IN_REPLY = ("RP-", "fraud", "audit", "idempotency", "reviewer")


def _keyword_intent(text: str) -> Intent:
    t = text.lower()
    if any(k in t for k in ("refund", "money back", "return", "reimburse", "chargeback")):
        return "refund_request"
    if any(k in t for k in ("where is", "tracking", "status", "shipped")):
        return "order_status"
    if any(k in t for k in ("angry", "terrible", "complain", "awful")):
        return "complaint"
    return "other"


def classify_intent_ex(llm: BaseChatModel, message: str) -> tuple[Intent, bool]:
    """(intent, degraded). Degrades to the keyword classifier if every model is down."""
    try:
        raw = llm.invoke([SystemMessage(CLASSIFY_SYSTEM), HumanMessage(message)]).content
    except ModelUnavailableError:
        return _keyword_intent(message), True
    label = str(raw).strip().lower()
    for intent in INTENTS:
        if intent in label:
            return intent, False
    return _keyword_intent(message), False  # guard: model returned junk


def classify_intent(llm: BaseChatModel, message: str) -> Intent:
    return classify_intent_ex(llm, message)[0]


_TEMPLATES = {
    "refund_issued": (
        "Good news! We've issued a refund of ${amount:.2f} for order {order_id} "
        "(reference {refund_id}). It should appear on your original payment method in "
        "5-10 business days."
    ),
    "refund_denied": (
        "Thanks for reaching out about order {order_id}. Unfortunately it isn't eligible "
        "for a refund: {reason} If you think this is a mistake, just reply and we'll take a look."
    ),
    "refund_rejected_by_reviewer": (
        "Thanks for your patience with order {order_id}. After review we're unable to approve "
        "this refund. A support specialist will follow up with other options."
    ),
    "escalated_to_agent": (
        "Thanks for contacting us. We couldn't verify the account details for this request, so "
        "a support specialist will reach out to you directly."
    ),
    "fraud_review": (
        "Thanks for contacting us about order {order_id}. Your request needs an additional "
        "review before we can proceed; our team will contact you within 2 business days."
    ),
    "refund_queued": (
        "Thanks for your patience. Your refund for order {order_id} has been accepted and is "
        "queued for processing (reference {reference}). We'll email you as soon as the money "
        "has been sent; it has not been sent yet."
    ),
}


def template_reply(facts: dict) -> str:
    return _TEMPLATES[facts["next_action"]].format(
        **{"amount": 0.0, "refund_id": "", "reference": "", **facts}
    )


def mock_responder(messages: Sequence[BaseMessage]) -> str:
    """Deterministic stand-in for a real model, keyed on the TASK header."""
    system = str(messages[0].content) if messages else ""
    user = str(messages[-1].content)
    if system.startswith("TASK: CLASSIFY_INTENT"):
        return _keyword_intent(user)
    if system.startswith("TASK: WRITE_REPLY"):
        return template_reply(json.loads(user))
    return "[mock] unsupported task"


def write_reply_ex(llm: BaseChatModel, facts: dict) -> tuple[str, bool]:
    """(reply, degraded). Degrades to the vetted template if every model is down."""
    try:
        raw = str(
            llm.invoke([SystemMessage(REPLY_SYSTEM), HumanMessage(json.dumps(facts))]).content
        )
    except ModelUnavailableError:
        return template_reply(facts), True
    reply = raw.strip()
    # Output guard: fall back to a vetted template if the model misbehaves.
    if not reply or len(reply) > MAX_REPLY_CHARS or any(w in reply for w in _FORBIDDEN_IN_REPLY):
        return template_reply(facts), False
    return reply, False


def write_reply(llm: BaseChatModel, facts: dict) -> str:
    return write_reply_ex(llm, facts)[0]
