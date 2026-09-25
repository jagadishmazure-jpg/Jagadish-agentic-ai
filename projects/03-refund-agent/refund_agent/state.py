"""Typed state and structured output models."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

from pydantic import BaseModel, Field

Intent = Literal["refund_request", "order_status", "complaint", "other"]
NextAction = Literal[
    "refund_issued",
    "refund_denied",
    "refund_rejected_by_reviewer",
    "escalated_to_agent",
    "fraud_review",
]
Route = Literal["auto_refund", "human_approval", "deny", "fraud_review", "escalate"]


class RefundRequest(BaseModel):
    """Inbound request from the support channel."""

    request_id: str
    customer_id: str
    email: str
    order_id: str
    message: str


class FinalReply(BaseModel):
    """Structured output returned to the channel / caller."""

    intent: Intent
    citations: list[str] = Field(default_factory=list)
    next_action: NextAction
    customer_safe_reply: str


class RefundState(TypedDict, total=False):
    # input
    request: dict[str, Any]
    # derived
    intent: Intent
    identity_verified: bool
    identity_reason: str
    order: dict[str, Any] | None
    amount: float
    eligible: bool
    eligibility_reason: str
    fraud_flags: list[str]
    route: Route
    approval: dict[str, Any] | None
    refund: dict[str, Any] | None
    outcome: NextAction
    # accumulated across nodes (reducer = list concat)
    citations: Annotated[list[str], operator.add]
    trace: Annotated[list[str], operator.add]
    # output
    final: dict[str, Any]
