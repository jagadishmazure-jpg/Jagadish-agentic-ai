"""Mock enterprise systems.

- ``SalesWarehouse``   stands in for a Databricks lakehouse / demand agent (reached via A2A).
- ``Erp``              stands in for SAP (stock, open POs, MRP params, PO drafts + submit).
- ``SupplierNetwork``  stands in for a supplier portal / Ariba quote API.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any


class POAlreadyReleasedError(ValueError):
    """Business error: the draft's state does not allow the requested transition."""


class SalesWarehouse:
    def __init__(self, weekly_sales: dict[str, list[int]]):
        self._sales = weekly_sales

    def history(self, sku: str) -> list[int]:
        return list(self._sales.get(sku, []))


class Erp:
    def __init__(self, stock: dict[str, dict[str, Any]], open_pos: dict[str, list[dict]]):
        self._stock = stock
        self._open_pos = open_pos
        self.drafts: dict[str, dict[str, Any]] = {}
        self.submitted: list[dict[str, Any]] = []  # real POs sent to suppliers
        self._by_key: dict[str, dict[str, Any]] = {}
        self.submit_calls = 0
        self._draft_ids = itertools.count(1)
        self._po_ids = itertools.count(4500000001)

    def stock(self, sku: str) -> dict[str, Any] | None:
        s = self._stock.get(sku)
        return dict(s) if s else None

    def open_pos(self, sku: str) -> list[dict[str, Any]]:
        return [dict(p) for p in self._open_pos.get(sku, [])]

    def create_draft(self, **po: Any) -> dict[str, Any]:
        draft = {"draft_id": f"DRAFT-{next(self._draft_ids):03d}", "status": "draft", **po}
        self.drafts[draft["draft_id"]] = draft
        return dict(draft)

    def cancel_draft(self, draft_id: str, reason: str) -> dict[str, Any]:
        """Compensation for a draft that will not be released. Refused once submitted."""
        draft = self.drafts[draft_id]
        if draft["status"] == "submitted":
            raise POAlreadyReleasedError(f"{draft_id} already released to the supplier")
        draft.update(status="cancelled", cancel_reason=reason)
        return dict(draft)

    def submit(self, *, idempotency_key: str, draft_id: str) -> dict[str, Any]:
        """Idempotent: the same key returns the original PO; a supplier never gets two."""
        self.submit_calls += 1
        if idempotency_key in self._by_key:
            return {**self._by_key[idempotency_key], "replayed": True}
        if self.drafts[draft_id]["status"] == "cancelled":
            raise POAlreadyReleasedError(f"{draft_id} was cancelled; raise a new draft")
        po = {**self.drafts[draft_id], "status": "submitted", "po_number": str(next(self._po_ids))}
        self.drafts[draft_id]["status"] = "submitted"
        self._by_key[idempotency_key] = po
        self.submitted.append(po)
        return {**po, "replayed": False}


class SupplierNetwork:
    def __init__(self, catalog: dict[str, list[dict[str, Any]]], unavailable: set[str]):
        self._catalog = catalog
        self._unavailable = unavailable

    def suppliers(self, sku: str) -> list[dict[str, Any]]:
        return [
            {"supplier": s["supplier"], "preferred": s["preferred"]}
            for s in self._catalog.get(sku, [])
        ]

    def quote(self, supplier: str, sku: str, qty: int) -> dict[str, Any]:
        for s in self._catalog.get(sku, []):
            if s["supplier"] == supplier:
                if supplier in self._unavailable:
                    return {"supplier": supplier, "available": False, "error": "quote API timeout"}
                return {
                    "supplier": supplier,
                    "available": True,
                    "unit_price": s["unit_price"],
                    "lead_time_days": s["lead_time_days"],
                    "moq": s["moq"],
                    "qty": max(qty, s["moq"]),
                    **({"note": s["note"]} if s.get("note") else {}),
                }
        return {"supplier": supplier, "available": False, "error": "unknown supplier"}


class Notifier:
    """Posts to the buyer channel after submit. Supports fault injection."""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.fail_next = 0

    def send(self, text: str) -> None:
        if self.fail_next:
            self.fail_next -= 1
            raise ConnectionError("notification service unavailable")
        self.sent.append(text)


@dataclass
class Services:
    sales: SalesWarehouse
    erp: Erp
    suppliers: SupplierNetwork
    notifier: Notifier = field(default_factory=Notifier)


def seed_services() -> Services:
    """Four deterministic scenarios.

    SKU-100  reorder needed; preferred supplier is also the best quote.
    SKU-200  plenty of stock -> supervisor finishes without the supplier agent.
    SKU-300  preferred supplier's quote API is down -> fallback supplier.
    SKU-400  preferred supplier is pricier than an acceptable alternative -> reviewer loop.
    """
    sales = {
        "SKU-100": [100, 110, 105, 120, 115, 125, 130, 135],
        "SKU-200": [50, 48, 52, 50, 49, 51, 50, 50],
        "SKU-300": [40, 42, 45, 44, 46, 48, 50, 52],
        "SKU-400": [80, 80, 82, 85, 84, 86, 88, 90],
    }
    stock = {
        "SKU-100": {"on_hand": 200, "safety_stock": 60, "reorder_point": 300, "lead_time_days": 7},
        "SKU-200": {"on_hand": 600, "safety_stock": 40, "reorder_point": 140, "lead_time_days": 7},
        "SKU-300": {"on_hand": 30, "safety_stock": 25, "reorder_point": 90, "lead_time_days": 10},
        "SKU-400": {"on_hand": 120, "safety_stock": 50, "reorder_point": 220, "lead_time_days": 10},
    }
    open_pos = {
        "SKU-100": [{"po_number": "4500000901", "qty": 100, "eta_days": 5}],
        "SKU-400": [{"po_number": "4500000902", "qty": 40, "eta_days": 3}],
    }
    catalog = {
        "SKU-100": [
            {
                "supplier": "Acme",
                "preferred": True,
                "unit_price": 4.10,
                "lead_time_days": 7,
                "moq": 100,
            },
            {
                "supplier": "Globex",
                "preferred": False,
                "unit_price": 3.95,
                "lead_time_days": 21,
                "moq": 200,
            },
            {
                "supplier": "Initech",
                "preferred": False,
                "unit_price": 4.25,
                "lead_time_days": 5,
                "moq": 50,
            },
        ],
        "SKU-200": [
            {
                "supplier": "Acme",
                "preferred": True,
                "unit_price": 2.00,
                "lead_time_days": 7,
                "moq": 100,
            },
        ],
        "SKU-300": [
            {
                "supplier": "Umbrella",
                "preferred": True,
                "unit_price": 7.00,
                "lead_time_days": 7,
                "moq": 50,
            },
            {
                "supplier": "Stark",
                "preferred": False,
                "unit_price": 7.50,
                "lead_time_days": 10,
                "moq": 50,
            },
            {
                "supplier": "Wayne",
                "preferred": False,
                "unit_price": 7.20,
                "lead_time_days": 30,
                "moq": 50,
            },
        ],
        "SKU-400": [
            {
                "supplier": "Hooli",
                "preferred": True,
                "unit_price": 5.00,
                "lead_time_days": 7,
                "moq": 100,
            },
            {
                "supplier": "PiedPiper",
                "preferred": False,
                "unit_price": 4.60,
                "lead_time_days": 10,
                "moq": 100,
            },
        ],
    }
    return Services(
        sales=SalesWarehouse(sales),
        erp=Erp(stock, open_pos),
        suppliers=SupplierNetwork(catalog, unavailable={"Umbrella"}),
    )
