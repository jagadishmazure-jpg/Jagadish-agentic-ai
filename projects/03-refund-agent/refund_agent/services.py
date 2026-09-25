"""In-memory mock services. Swap each for a real client behind the same interface."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any


class OrdersDB:
    def __init__(self, orders: dict[str, dict[str, Any]]):
        self._orders = orders

    def get(self, order_id: str) -> dict[str, Any] | None:
        order = self._orders.get(order_id)
        return dict(order) if order else None

    def mark_refunded(self, order_id: str, refund_id: str) -> None:
        self._orders[order_id]["status"] = "refunded"
        self._orders[order_id]["refund_id"] = refund_id


class CustomerDirectory:
    def __init__(self, customers: dict[str, dict[str, Any]]):
        self._customers = customers

    def verify(self, customer_id: str, email: str) -> bool:
        c = self._customers.get(customer_id)
        return bool(c) and c["email"].lower() == email.strip().lower()


class RefundAPI:
    """Mock payment provider. Idempotent: same key -> same refund, money moves once."""

    def __init__(self) -> None:
        self._by_key: dict[str, dict[str, Any]] = {}
        self.ledger: list[dict[str, Any]] = []  # every real money movement
        self.calls = 0
        self._ids = itertools.count(1)

    def issue(self, *, idempotency_key: str, order_id: str, amount: float) -> dict[str, Any]:
        self.calls += 1
        if idempotency_key in self._by_key:
            return {**self._by_key[idempotency_key], "replayed": True}
        refund = {
            "refund_id": f"rf_{next(self._ids):04d}",
            "order_id": order_id,
            "amount": round(amount, 2),
            "status": "succeeded",
            "replayed": False,
        }
        self._by_key[idempotency_key] = refund
        self.ledger.append(refund)
        return refund


class CRM:
    def __init__(self) -> None:
        self.notes: list[dict[str, str]] = []
        self.fail_next = 0  # fault injection for tests

    def add_note(self, customer_id: str, note: str) -> None:
        if self.fail_next:
            self.fail_next -= 1
            raise ConnectionError("CRM temporarily unavailable")
        self.notes.append({"customer_id": customer_id, "note": note})


class AuditLog:
    """Append-only audit trail (who/what/why for every decision)."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def record(self, request_id: str, event: str, **details: Any) -> None:
        self.entries.append(
            {
                "ts": datetime.now(UTC).isoformat(timespec="seconds"),
                "request_id": request_id,
                "event": event,
                **details,
            }
        )

    def events(self, request_id: str | None = None) -> list[str]:
        return [
            e["event"] for e in self.entries if request_id is None or e["request_id"] == request_id
        ]


@dataclass
class Services:
    orders: OrdersDB
    customers: CustomerDirectory
    refunds: RefundAPI = field(default_factory=RefundAPI)
    crm: CRM = field(default_factory=CRM)
    audit: AuditLog = field(default_factory=AuditLog)
    today: date = field(default_factory=date.today)


def seed_services(today: date | None = None) -> Services:
    """Deterministic fixture data used by the demo and tests."""
    today = today or date(2026, 9, 25)
    d = lambda days: today - timedelta(days=days)  # noqa: E731
    orders = {
        "A100": {
            "order_id": "A100",
            "customer_id": "C1",
            "amount": 24.99,
            "category": "apparel",
            "status": "delivered",
            "delivered_on": d(5),
        },
        "A200": {
            "order_id": "A200",
            "customer_id": "C1",
            "amount": 349.00,
            "category": "electronics",
            "status": "delivered",
            "delivered_on": d(10),
        },
        "A300": {
            "order_id": "A300",
            "customer_id": "C2",
            "amount": 80.00,
            "category": "home",
            "status": "delivered",
            "delivered_on": d(45),
        },
        "A400": {
            "order_id": "A400",
            "customer_id": "C2",
            "amount": 19.00,
            "category": "books",
            "status": "refunded",
            "delivered_on": d(3),
        },
        "A500": {
            "order_id": "A500",
            "customer_id": "C3",
            "amount": 120.00,
            "category": "electronics",
            "status": "delivered",
            "delivered_on": d(2),
        },
        "A600": {
            "order_id": "A600",
            "customer_id": "C3",
            "amount": 25.00,
            "category": "gift_card",
            "status": "delivered",
            "delivered_on": d(1),
        },
    }
    customers = {
        "C1": {"email": "ana@example.com"},
        "C2": {"email": "bo@example.com"},
        "C3": {"email": "cy@example.com"},
    }
    return Services(orders=OrdersDB(orders), customers=CustomerDirectory(customers), today=today)
