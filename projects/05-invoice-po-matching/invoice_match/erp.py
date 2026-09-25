"""Mock ERP with typed errors (business vs transient) and idempotent invoice posting."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any


class ERPError(Exception):
    """Base class for ERP errors."""


class PONotFoundError(ERPError):
    pass


class POClosedError(ERPError):
    pass


class ERPUnavailableError(ERPError):
    """Transient: retried by the graph's RetryPolicy, never turned into a business exception."""


@dataclass
class MockERP:
    pos: dict[str, dict[str, Any]]
    receipts: dict[str, list[dict[str, Any]]]
    posted: dict[str, dict[str, Any]] = field(default_factory=dict)  # invoice_number -> doc
    unavailable_for: int = 0  # next N calls raise ERPUnavailableError
    calls: int = 0
    _docs: Any = field(default_factory=lambda: itertools.count(5100000001))

    def _io(self) -> None:
        self.calls += 1
        if self.unavailable_for > 0:
            self.unavailable_for -= 1
            raise ERPUnavailableError("ERP gateway 503")

    def get_po(self, po_number: str) -> dict[str, Any]:
        self._io()
        po = self.pos.get(po_number)
        if po is None:
            raise PONotFoundError(f"PO {po_number} does not exist")
        if po["status"] == "closed":
            raise POClosedError(f"PO {po_number} is closed")
        return {**po, "lines": [dict(ln) for ln in po["lines"]]}

    def get_receipts(self, po_number: str) -> dict[str, float]:
        """Received quantity per SKU (sum of goods receipts)."""
        received: dict[str, float] = {}
        for gr in self.receipts.get(po_number, []):
            received[gr["sku"]] = received.get(gr["sku"], 0) + gr["qty"]
        return received

    def invoiced_qty(self, po_number: str) -> dict[str, float]:
        """Quantity already invoiced (posted) per SKU against this PO."""
        out: dict[str, float] = {}
        for rec in self.posted.values():
            inv = rec["invoice"]
            if inv["po_number"] == po_number:
                for ln in inv["lines"]:
                    out[ln["sku"]] = out.get(ln["sku"], 0) + ln["qty"]
        return out

    def is_posted(self, invoice_number: str) -> bool:
        return invoice_number in self.posted

    def post_invoice(self, invoice: dict[str, Any]) -> str:
        """Idempotent on invoice number: re-posting returns the original document."""
        key = invoice["invoice_number"]
        if key not in self.posted:
            self.posted[key] = {"doc": str(next(self._docs)), "invoice": invoice}
        return self.posted[key]["doc"]


def seed_erp() -> MockERP:
    pos = {
        "PO-5001": {
            "vendor": "Acme Industrial Supply",
            "currency": "USD",
            "status": "open",
            "lines": [
                {"sku": "BOLT-10", "qty": 20, "unit_price": 12.50},
                {"sku": "NUT-10", "qty": 20, "unit_price": 8.00},
                {"sku": "WASH-10", "qty": 50, "unit_price": 12.60},
            ],
        },
        "PO-5002": {
            "vendor": "Globex Components",
            "currency": "USD",
            "status": "open",
            "lines": [
                {"sku": "MTR-200", "qty": 10, "unit_price": 240.00},
                {"sku": "CBL-5", "qty": 100, "unit_price": 3.20},
            ],
        },
        "PO-5009": {
            "vendor": "Initech Tools",
            "currency": "USD",
            "status": "closed",
            "lines": [{"sku": "DRL-1", "qty": 5, "unit_price": 99.00}],
        },
    }
    receipts = {
        "PO-5001": [
            {"gr": "GR-1", "sku": "BOLT-10", "qty": 20},
            {"gr": "GR-2", "sku": "NUT-10", "qty": 20},
            {"gr": "GR-3", "sku": "WASH-10", "qty": 50},
        ],
        "PO-5002": [
            {"gr": "GR-7", "sku": "MTR-200", "qty": 8},  # partial delivery
            {"gr": "GR-8", "sku": "CBL-5", "qty": 100},
        ],
    }
    return MockERP(pos=pos, receipts=receipts)
