"""Systems of record behind MCP, one scoped ToolGateway per agent (least privilege).

- ``analytics``  certified semantic model over the sales lakehouse (``weekly_units`` measure)
- ``erp``        SAP-like stock / open POs / PO drafts / release / draft cancellation
- ``suppliers``  supplier portal quote network (external: its text is untrusted)

Each specialist gets a gateway whose allowlist is exactly its job; the orchestrator
(``submit_po`` node) is the only identity that can release or cancel a PO, and only after
human approval. Gateways validate payload schemas, retry transient errors with backoff,
trip a per-system circuit breaker and neutralise injected instructions in returned text.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from shared.resilience import Backoff
from shared.tools import ToolGateway, connect_backends
from supply_chain.services import POAlreadyReleasedError, Services

SCOPES: dict[str, tuple[str, set[str]]] = {
    # agent -> (managed identity, allowlist)
    "demand": ("mi-demand-planner", {"analytics.get_measure"}),
    "inventory": ("mi-inventory-reader", {"erp.get_stock", "erp.get_open_purchase_orders"}),
    "supplier": (
        "mi-sourcing-drafter",
        {"suppliers.list_suppliers", "suppliers.get_supplier_quote", "erp.create_po_draft"},
    ),
    "orchestrator": ("mi-po-releaser", {"erp.submit_purchase_order", "erp.cancel_po_draft"}),
}


class Stock(BaseModel):
    """Contract for erp.get_stock payloads (tool output is untrusted)."""

    model_config = ConfigDict(extra="allow")
    on_hand: int
    safety_stock: int
    reorder_point: int
    lead_time_days: int


class Quote(BaseModel):
    model_config = ConfigDict(extra="allow")
    supplier: str
    available: bool
    unit_price: float | None = None
    lead_time_days: int | None = None
    moq: int | None = None


class AnalyticsBackend:
    def __init__(self, s: Services):
        self.s = s

    def get_measure(self, measure: str, entity: str, grain: str) -> dict[str, Any]:
        if measure != "weekly_units" or grain != "week":
            raise KeyError(f"no certified measure {measure}@{grain}")
        return {
            "measure": measure,
            "entity": entity,
            "grain": grain,
            "values": self.s.sales.history(entity),
        }


class ErpBackend:
    def __init__(self, s: Services):
        self.erp = s.erp

    def get_stock(self, sku: str) -> dict[str, Any]:
        return self.erp.stock(sku) or {
            "on_hand": 0,
            "safety_stock": 0,
            "reorder_point": 0,
            "lead_time_days": 0,
        }

    def get_open_purchase_orders(self, sku: str) -> list[dict[str, Any]]:
        return self.erp.open_pos(sku)

    def create_po_draft(self, po: dict[str, Any]) -> dict[str, Any]:
        return self.erp.create_draft(**po)

    def submit_purchase_order(self, draft_id: str, key: str) -> dict[str, Any]:
        return self.erp.submit(idempotency_key=key, draft_id=draft_id)

    def cancel_po_draft(self, draft_id: str, reason: str) -> dict[str, Any]:
        return self.erp.cancel_draft(draft_id, reason)


class SuppliersBackend:
    def __init__(self, s: Services):
        self.net = s.suppliers

    def list_suppliers(self, sku: str) -> list[dict[str, Any]]:
        return self.net.suppliers(sku)

    def get_supplier_quote(self, supplier: str, sku: str, qty: int) -> dict[str, Any]:
        return self.net.quote(supplier, sku, qty)


def build_gateways(services: Services) -> dict[str, ToolGateway]:
    conns = connect_backends(
        {
            "analytics": AnalyticsBackend(services),
            "erp": ErpBackend(services),
            "suppliers": SuppliersBackend(services),
        }
    )
    return {
        agent: ToolGateway(
            f"{agent}_agent" if agent != "orchestrator" else "supply-orchestrator",
            identity,
            conns,
            allow,
            schemas={"erp.get_stock": Stock, "suppliers.get_supplier_quote": Quote},
            error_types={
                "KeyError": KeyError,
                "POAlreadyReleasedError": POAlreadyReleasedError,
            },
            retry=Backoff(attempts=2, base_s=0.05),
            timeout_s=5.0,
        )
        for agent, (identity, allow) in SCOPES.items()
    }
