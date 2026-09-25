"""Refund policy: deterministic rules with citable IDs."""

from __future__ import annotations

from datetime import date

POLICY: dict[str, str] = {
    "RP-1": "Refunds require verified customer identity (customer id + email on file).",
    "RP-2": "Refunds are available within 30 days of delivery.",
    "RP-3": "An order can be refunded at most once.",
    "RP-4": "Gift cards and final-sale items are non-refundable.",
    "RP-5": "Refunds under $50.00 are approved automatically.",
    "RP-6": "Refunds of $50.00 or more require human approval.",
    "RP-7": "Requests with fraud indicators go to the fraud team before any money moves.",
}

REFUND_WINDOW_DAYS = 30
AUTO_APPROVE_LIMIT = 50.00
NON_REFUNDABLE_CATEGORIES = {"gift_card", "final_sale"}
FRAUD_KEYWORDS = (
    "chargeback",
    "stolen card",
    "someone else's card",
    "not my card",
    "different account",
    "send it to another card",
    "wire the money",
    "gift card instead",
    "bitcoin",
)


def cite(rule_id: str) -> str:
    return f"{rule_id}: {POLICY[rule_id]}"


def fraud_flags(message: str) -> list[str]:
    text = message.lower()
    return [kw for kw in FRAUD_KEYWORDS if kw in text]


def check_eligibility(order: dict | None, today: date) -> tuple[bool, str, str | None]:
    """Return (eligible, reason, citation-or-None)."""
    if order is None:
        return False, "Order not found for this customer.", cite("RP-3")
    if order["status"] == "refunded":
        return False, "Order has already been refunded.", cite("RP-3")
    if order["category"] in NON_REFUNDABLE_CATEGORIES:
        return False, f"Category '{order['category']}' is non-refundable.", cite("RP-4")
    age = (today - order["delivered_on"]).days
    if age > REFUND_WINDOW_DAYS:
        return False, f"Delivered {age} days ago (window is {REFUND_WINDOW_DAYS}).", cite("RP-2")
    return True, f"Within {REFUND_WINDOW_DAYS}-day window ({age} days).", cite("RP-2")
