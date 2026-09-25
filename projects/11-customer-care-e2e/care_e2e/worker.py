"""Outbox worker (Service Bus consumer stand-in): the only code path that moves money.

``dispatch`` is at-least-once; the payment provider dedupes on the idempotency key, so a
redelivery after a timeout never pays twice. A slow or down provider leaves the command
queued - the customer already has an honest 'queued, reference CS-...' message.
"""

from __future__ import annotations

from typing import Any

from care_e2e.systems import Systems
from shared.tools import SystemOfRecordUnavailableError, ToolGateway


def dispatch(s: Systems, gw: ToolGateway, item: dict[str, Any]) -> bool:
    if item["status"] == "done":
        return True
    item["attempts"] += 1
    try:
        r = gw.call(
            "payments",
            "issue_refund",
            order_id=item["order_id"],
            amount=item["amount"],
            idempotency_key=item["key"],
            dry_run=False,
        )
    except SystemOfRecordUnavailableError as exc:
        item["last_error"] = str(exc)
        return False
    item.update(status="done", refund_id=r["refund_id"])
    for server, tool, args in (
        ("oms", "mark_order_refunded", {"order_id": item["order_id"], "refund_id": r["refund_id"]}),
        (
            "crm",
            "add_case_note",
            {
                "customer_id": item["customer_id"],
                "note": f"Refund {r['refund_id']} issued ({item['amount']})",
            },
        ),
    ):
        try:  # follow-ups are best effort: the money state is already correct
            gw.call(server, tool, idempotency_key=f"{item['key']}:{tool}", dry_run=False, **args)
        except SystemOfRecordUnavailableError:
            item.setdefault("pending_followups", []).append(tool)
    return True


def drain(s: Systems, gw: ToolGateway) -> int:
    """Redeliver every queued command; returns how many completed."""
    return sum(dispatch(s, gw, item) for item in s.outbox.queued())
