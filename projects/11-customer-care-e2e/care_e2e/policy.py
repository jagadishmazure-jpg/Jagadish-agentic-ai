"""Deterministic refund rules per policy edition (the corpus supplies the citable text).

The model never decides eligibility or amounts: it drafts wording around these numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

AUTO_REFUND_LIMIT = 50.00  # CARE-AUTO-1: above this a human approves
CONFIDENCE_GATE = 0.6  # classifier confidence below this -> ask a clarifying question
MAX_TOOL_CALLS = 8  # planner budget per request
MAX_REPAIRS = 1  # critic: repair once, then escalate
HITL_SLA_HOURS = 4


@dataclass(frozen=True)
class Edition:
    policy_id: str
    shipping_refund_days: int  # late >= N days -> refund shipping fee
    full_refund_days: int | None  # late >= N days -> refund whole order (None: lost only)


EDITIONS = {
    "CARE-LATE-2025": Edition("CARE-LATE-2025", 7, None),
    "CARE-LATE-2026": Edition("CARE-LATE-2026", 5, 10),
}


def plural(n: int, word: str = "day") -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def days_late(order: dict[str, Any], today: date) -> int:
    promised = date.fromisoformat(order["promised_date"])
    end = date.fromisoformat(order["delivered_on"]) if order.get("delivered_on") else today
    return max(0, (end - promised).days)


def decide(order: dict[str, Any], edition_id: str, today: date) -> dict[str, Any]:
    """Refund proposal from order facts + the edition in force on the purchase date."""
    ed = EDITIONS[edition_id]
    late = days_late(order, today)
    if order["status"] == "lost":
        amount, basis = order["amount"] + order["shipping_fee"], "lost shipment: full refund"
    elif ed.full_refund_days is not None and late >= ed.full_refund_days:
        amount, basis = order["amount"] + order["shipping_fee"], f"{plural(late)} late: full refund"
    elif late >= ed.shipping_refund_days:
        amount, basis = order["shipping_fee"], f"{plural(late)} late: shipping fee refund"
    else:
        amount, basis = (
            0.0,
            f"{plural(late)} late, below the {ed.shipping_refund_days}-day threshold",
        )
    amount = round(amount, 2)
    return {
        "eligible": amount > 0,
        "amount": amount,
        "days_late": late,
        "basis": basis,
        "policy_id": ed.policy_id,
        "needs_human": amount > AUTO_REFUND_LIMIT,
    }
