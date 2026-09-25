"""OMS, CRM and the payment provider behind MCP (shared domain servers), reached only through
tool gateways with the care agent's identities.

Two identities: ``mi-care-reader`` (reads, used by the care graph) and ``mi-refund-writer``
(the outbox worker: the only identity that can move money).
"""

from __future__ import annotations

import os
from typing import Any

from pydantic import BaseModel, ConfigDict

from care_e2e.systems import OrderNotFoundError, Systems
from shared.resilience import Backoff
from shared.tools import ToolGateway, connect_backends, connect_urls

READER = (
    "care-graph",
    "mi-care-reader",
    {
        "oms.get_order",
        "crm.verify_customer",
        "crm.get_account",
        "crm.get_contact_history",
    },
)
WRITER = (
    "refund-worker",
    "mi-refund-writer",
    {
        "payments.issue_refund",
        "oms.mark_order_refunded",
        "crm.add_case_note",
    },
)


class Order(BaseModel):
    """Contract for oms.get_order (tool output is untrusted and validated)."""

    model_config = ConfigDict(extra="allow")
    order_id: str
    customer_id: str
    amount: float
    shipping_fee: float
    purchase_date: str
    promised_date: str
    status: str


class OmsBackend:
    def __init__(self, s: Systems):
        self.s = s

    def get_order(self, order_id: str) -> dict[str, Any]:
        if order_id not in self.s.orders:
            raise OrderNotFoundError(f"order {order_id} not found")
        return dict(self.s.orders[order_id])

    def mark_order_refunded(self, order_id: str, refund_id: str) -> dict[str, Any]:
        self.s.orders[order_id]["refund_id"] = refund_id
        return {"order_id": order_id, "refund_id": refund_id}


class CrmBackend:
    def __init__(self, s: Systems):
        self.s = s

    def verify_customer(self, customer_id: str, email: str) -> bool:
        c = self.s.customers.get(customer_id)
        return bool(c and c["email"].lower() == email.lower())

    def get_account(self, account_id: str) -> dict[str, Any]:
        c = self.s.customers[account_id]
        return {"customer_id": c["customer_id"], "risk_flag": c["risk_flag"], "tenant": c["tenant"]}

    def get_contact_history(self, account_id: str) -> list[dict[str, Any]]:
        return [dict(c) for c in self.s.cases.get(account_id, [])]

    def add_case_note(self, customer_id: str, note: str) -> dict[str, Any]:
        self.s.notes.append({"customer_id": customer_id, "note": note})
        return {"ok": True}


class PaymentsBackend:
    def __init__(self, s: Systems):
        self.s = s

    def issue_refund(self, order_id: str, amount: float, key: str) -> dict[str, Any]:
        return self.s.payments.issue_refund(order_id, amount, key)


def backends(s: Systems) -> dict[str, Any]:
    return {"oms": OmsBackend(s), "crm": CrmBackend(s), "payments": PaymentsBackend(s)}


def build_gateways(s: Systems) -> dict[str, ToolGateway]:
    """In-process MCP servers by default; ``CARE_MCP_URLS=oms=http://mcp-oms:8000/mcp,...``
    (docker-compose / Container Apps) switches to remote servers over streamable HTTP."""
    urls = os.getenv("CARE_MCP_URLS")
    conns = (
        connect_urls(dict(kv.split("=", 1) for kv in urls.split(",")))
        if urls
        else connect_backends(backends(s))
    )
    errs = {"OrderNotFoundError": OrderNotFoundError, "KeyError": KeyError}
    reader = ToolGateway(
        READER[0],
        READER[1],
        conns,
        READER[2],
        schemas={"oms.get_order": Order},
        error_types=errs,
        retry=Backoff(attempts=2, base_s=0.05),
        timeout_s=3.0,
    )
    # the outbox is the retry mechanism for writes: fail fast, stay queued, redeliver later
    writer = ToolGateway(
        WRITER[0],
        WRITER[1],
        conns,
        WRITER[2],
        error_types=errs,
        retry=None,
        timeout_s=0.5,
    )
    return {"reader": reader, "writer": writer}
