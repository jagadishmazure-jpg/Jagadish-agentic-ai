"""Structured classification schema and routing tables."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Intent = Literal[
    "billing", "technical", "account_access", "feature_request", "cancellation", "other"
]
Urgency = Literal["low", "medium", "high", "critical"]
Product = Literal["payments", "mobile_app", "web_dashboard", "api", "unknown"]


class TicketClassification(BaseModel):
    """What the LLM must return. Validated strictly; invalid output triggers a repair prompt."""

    intent: Intent
    urgency: Urgency
    product: Product
    confidence: float = Field(ge=0.0, le=1.0)
    summary: str = Field(min_length=3, max_length=200)


QUEUES: dict[str, str] = {
    "billing": "billing_queue",
    "technical": "tech_support_queue",
    "account_access": "account_security_queue",
    "feature_request": "product_feedback_queue",
    "cancellation": "retention_queue",
}
SLA_HOURS: dict[str, int] = {"critical": 1, "high": 4, "medium": 24, "low": 72}

CONFIDENCE_FLOOR = 0.60  # below: don't auto-route
HUMAN_FLOOR = 0.40  # below: straight to a human (too unclear even to ask a good question)
MAX_REPAIRS = 1


class TriageResult(BaseModel):
    ticket_id: str
    route: Literal["queue", "clarify", "human_review"]
    queue: str | None = None
    sla_hours: int | None = None
    page_on_call: bool = False
    classification: TicketClassification | None = None
    redactions: dict[str, int] = Field(default_factory=dict)
    repair_attempts: int = 0
    reason: str
    customer_reply: str
    ticket_ref: str | None = None  # service-desk ticket id (None: queued in the outbox)
