"""The ERP (SAP-like purchasing / receiving / AP) behind MCP.

The graph reaches it only through a ToolGateway with the AP agent's identity and allowlist.
Business errors (PO not found / closed) cross the wire as typed envelopes and are re-raised
as the same exception types; ERP outages are retryable and surface as
``SystemOfRecordUnavailableError`` (the graph maps them to ``ERPUnavailableError`` so its
node RetryPolicy keeps working).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from invoice_match.erp import MockERP, POClosedError, PONotFoundError
from shared.tools import ToolGateway, connect_backends

AGENT = "invoice-matcher"
IDENTITY = "mi-ap-invoice-matcher"
ALLOW = {
    "erp.get_purchase_order",
    "erp.get_goods_receipts",
    "erp.get_invoiced_quantities",
    "erp.is_invoice_posted",
    "erp.post_invoice",  # write: only after a clean three-way match, idempotent on invoice no.
}


class POLine(BaseModel):
    sku: str
    qty: float
    unit_price: float


class PurchaseOrder(BaseModel):
    """Contract for erp.get_purchase_order payloads (tool output is untrusted)."""

    model_config = ConfigDict(extra="allow")
    vendor: str
    currency: str
    status: Literal["open", "closed"]
    lines: list[POLine]


class ErpBackend:
    def __init__(self, erp: MockERP):
        self.erp = erp

    def get_purchase_order(self, po_number: str) -> dict[str, Any]:
        return self.erp.get_po(po_number)

    def get_goods_receipts(self, po_number: str) -> dict[str, float]:
        return self.erp.get_receipts(po_number)

    def get_invoiced_quantities(self, po_number: str) -> dict[str, float]:
        return self.erp.invoiced_qty(po_number)

    def is_invoice_posted(self, invoice_number: str) -> bool:
        return self.erp.is_posted(invoice_number)

    def post_invoice(self, invoice: dict[str, Any]) -> str:
        return self.erp.post_invoice(invoice)


def build_gateway(erp: MockERP) -> ToolGateway:
    return ToolGateway(
        AGENT,
        IDENTITY,
        connect_backends({"erp": ErpBackend(erp)}),
        ALLOW,
        schemas={"erp.get_purchase_order": PurchaseOrder},
        error_types={"PONotFoundError": PONotFoundError, "POClosedError": POClosedError},
        timeout_s=5.0,
        retry=None,  # the fetch_erp node's RetryPolicy owns retries
    )
