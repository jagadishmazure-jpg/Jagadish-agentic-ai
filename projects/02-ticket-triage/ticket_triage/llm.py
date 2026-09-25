"""Classification / repair prompts and a deterministic keyword-based mock."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

from langchain_core.messages import BaseMessage

from ticket_triage.schema import TicketClassification

CLASSIFY_SYSTEM = (
    "TASK: CLASSIFY\n"
    "Classify the support ticket. Reply ONLY with JSON matching this schema:\n"
    + json.dumps(TicketClassification.model_json_schema())
    + "\nconfidence is your probability that intent is correct. Placeholders like [EMAIL_1] "
    "are redacted PII."
)
REPAIR_SYSTEM = (
    "TASK: REPAIR\n"
    "Your previous output failed schema validation. Return ONLY corrected JSON for the same "
    "ticket that satisfies the schema. Validation errors:\n{errors}"
)
CLARIFY_SYSTEM = (
    "TASK: CLARIFY\n"
    "Write one short, friendly question asking the customer for the missing details needed "
    "to route their ticket (product, what they were doing, error message)."
)

KEYWORDS: dict[str, tuple[str, ...]] = {
    "billing": ("invoice", "charged", "charge", "refund", "billing", "payment failed", "price"),
    "technical": ("error", "crash", "bug", "500", "timeout", "not loading", "broken", "fails"),
    "account_access": ("password", "locked", "login", "log in", "2fa", "mfa", "sign in"),
    "feature_request": ("feature", "would be great", "please add", "suggestion", "wish"),
    "cancellation": ("cancel", "close my account", "switching to", "terminate"),
}
PRODUCTS: dict[str, tuple[str, ...]] = {
    "payments": ("payment", "card", "invoice", "checkout"),
    "mobile_app": ("app", "iphone", "android", "mobile"),
    "web_dashboard": ("dashboard", "browser", "website", "portal"),
    "api": ("api", "endpoint", "webhook", "sdk"),
}
CRITICAL = ("outage", "all customers", "production down", "data breach", "hacked", "down for")
HIGH = ("urgent", "asap", "cannot", "can't", "blocked", "immediately")


def keyword_classify(text: str) -> TicketClassification:
    t = text.lower()
    hits = {k: sum(w in t for w in words) for k, words in KEYWORDS.items()}
    intent, n = max(hits.items(), key=lambda kv: kv[1])
    if n == 0:
        intent = "other"
    product = next((p for p, ws in PRODUCTS.items() if any(w in t for w in ws)), "unknown")
    if any(w in t for w in CRITICAL):
        urgency = "critical"
    elif any(w in t for w in HIGH):
        urgency = "high"
    else:
        urgency = "low" if intent == "feature_request" else "medium"
    confidence = min(0.95, 0.35 + 0.2 * n)
    summary = re.sub(r"\s+", " ", text.strip())[:120] or "empty ticket"
    return TicketClassification(
        intent=intent, urgency=urgency, product=product, confidence=confidence, summary=summary
    )


def mock_responder(messages: Sequence[BaseMessage]) -> str:
    system = str(messages[0].content)
    ticket = str(next(m for m in messages if m.type == "human").content)
    if system.startswith(("TASK: CLASSIFY", "TASK: REPAIR")):
        return keyword_classify(ticket).model_dump_json()
    if system.startswith("TASK: CLARIFY"):
        return (
            "Thanks for reaching out! Could you tell us which product you're using "
            "(mobile app, web dashboard, API or payments) and any error message you saw?"
        )
    return "[mock] unsupported task"
