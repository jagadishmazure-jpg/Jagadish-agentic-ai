"""Mock systems of record + the outbox (Service Bus stand-in) and the approval queue.

OMS (orders + carrier scans), CRM (customers + case timeline with ACL groups and tenant),
payment provider (idempotent on key, optionally *slow*), and a durable outbox of write
commands drained by a worker.
"""

from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

TODAY = date(2026, 9, 25)
NOW = datetime(2026, 9, 25, 14, 0)
TENANT = "acme-retail"


class OrderNotFoundError(LookupError):
    pass


@dataclass
class Payments:
    """Provider-side idempotency: the same key never pays twice. ``delay_s`` simulates a slow
    provider (the gateway times out; the write stays queued in the outbox)."""

    delay_s: float = 0.0
    refunds: dict[str, dict[str, Any]] = field(default_factory=dict)
    calls: int = 0
    _ids: Any = field(default_factory=lambda: itertools.count(9001))
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def issue_refund(self, order_id: str, amount: float, key: str) -> dict[str, Any]:
        if self.delay_s:
            time.sleep(self.delay_s)
        with self._lock:
            self.calls += 1
            if key in self.refunds:
                return {**self.refunds[key], "replayed": True}
            r = {"refund_id": f"R-{next(self._ids)}", "order_id": order_id, "amount": amount}
            self.refunds[key] = r
            return {**r, "replayed": False}


@dataclass
class Outbox:
    """Transactional outbox: commands are written first, then dispatched (at least once);
    idempotency keys make redelivery safe."""

    items: dict[str, dict[str, Any]] = field(default_factory=dict)

    def put(self, key: str, command: dict[str, Any]) -> dict[str, Any]:
        item = self.items.setdefault(
            key, {"key": key, "status": "queued", "attempts": 0, "ticket": _ticket(key), **command}
        )
        return item

    def queued(self) -> list[dict[str, Any]]:
        return [i for i in self.items.values() if i["status"] == "queued"]


def _ticket(key: str) -> str:
    return "CS-" + key.split(":")[-1].replace("O-", "")


@dataclass
class Systems:
    customers: dict[str, dict[str, Any]]
    orders: dict[str, dict[str, Any]]
    cases: dict[str, list[dict[str, Any]]]
    payments: Payments = field(default_factory=Payments)
    outbox: Outbox = field(default_factory=Outbox)
    notes: list[dict[str, Any]] = field(default_factory=list)
    review_queue: list[dict[str, Any]] = field(default_factory=list)
    pending_approvals: dict[str, datetime] = field(default_factory=dict)
    now: datetime = NOW

    @property
    def today(self) -> date:
        return self.now.date()


def _order(oid, cust, amount, shipping, purchased, promised, status, delivered=None, scan=None):
    return {
        "order_id": oid,
        "customer_id": cust,
        "amount": amount,
        "shipping_fee": shipping,
        "purchase_date": purchased,
        "promised_date": promised,
        "status": status,  # in_transit | delivered | lost
        "delivered_on": delivered,
        "last_scan": scan or {},
        "refund_id": None,
    }


def seed_systems(now: datetime = NOW) -> Systems:
    customers = {
        "C100": {
            "customer_id": "C100",
            "name": "Ana Silva",
            "email": "ana@example.com",
            "tenant": TENANT,
            "risk_flag": False,
        },
        "C200": {
            "customer_id": "C200",
            "name": "Ben Ode",
            "email": "ben@example.com",
            "tenant": TENANT,
            "risk_flag": False,
        },
        "C300": {
            "customer_id": "C300",
            "name": "Cy Vale",
            "email": "cy@example.com",
            "tenant": TENANT,
            "risk_flag": True,
        },
    }
    scan = {"at": "2026-09-12T08:10", "location": "Memphis hub", "event": "delayed"}
    orders = {
        o["order_id"]: o
        for o in [
            _order(
                "O-1001", "C100", 42.00, 6.99, "2026-09-01", "2026-09-08", "in_transit", scan=scan
            ),
            _order(
                "O-1002", "C100", 38.50, 6.99, "2026-09-10", "2026-09-19", "in_transit", scan=scan
            ),
            _order(
                "O-1003", "C100", 55.00, 6.99, "2026-09-15", "2026-09-24", "in_transit", scan=scan
            ),
            _order(
                "O-1004",
                "C100",
                64.00,
                6.99,
                "2025-12-10",
                "2025-12-18",
                "delivered",
                delivered="2025-12-30",
            ),
            _order(
                "O-1005", "C100", 249.00, 0.0, "2026-09-01", "2026-09-10", "in_transit", scan=scan
            ),
            _order(
                "O-2001", "C200", 30.00, 6.99, "2026-09-01", "2026-09-08", "in_transit", scan=scan
            ),
            _order(
                "O-3001", "C300", 45.00, 6.99, "2026-09-01", "2026-09-08", "in_transit", scan=scan
            ),
            _order("O-1006", "C100", 22.00, 6.99, "2026-09-01", "2026-09-06", "lost", scan=scan),
        ]
    }
    cases = {
        "C100": [
            {
                "case_id": "CASE-11",
                "at": "2026-09-12",
                "groups": ["care"],
                "tenant": TENANT,
                "text": "Customer asked about O-1001 delay; told the carrier is investigating.",
            },
            {
                "case_id": "CASE-12",
                "at": "2026-09-13",
                "groups": ["billing"],
                "tenant": TENANT,
                "text": "Billing-only note: card on file updated; last4 on record.",
            },
        ],
        "C300": [
            {
                "case_id": "CASE-31",
                "at": "2026-09-02",
                "groups": ["fraud-ops"],
                "tenant": TENANT,
                "text": "Internal: account under refund-abuse review; route refund asks to fraud.",
            },
        ],
    }
    return Systems(customers, orders, cases, now=now)


def sla_due(now: datetime, hours: int = 4) -> datetime:
    return now + timedelta(hours=hours)
