"""Systems of record behind MCP: OMS, CRM and the payment provider, reached only through the
tool gateway with the refund agent's identity and allowlist."""

from __future__ import annotations

from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict

from refund_agent.services import Services
from shared.tools import ToolGateway, connect_backends

AGENT = "refund-agent"
IDENTITY = "mi-refund-agent"
ALLOW = {
    "oms.get_order",
    "oms.mark_order_refunded",  # OMS
    "crm.verify_customer",
    "crm.add_case_note",  # CRM
    "payments.issue_refund",  # payment provider (write, HITL-gated)
}


class OrderNotFoundError(LookupError):
    pass


class Order(BaseModel):
    """Contract for oms.get_order payloads (validated: tool output is untrusted)."""

    model_config = ConfigDict(extra="allow")
    order_id: str
    customer_id: str
    amount: float
    category: str
    status: str
    delivered_on: date


class OmsBackend:
    def __init__(self, s: Services):
        self.s = s

    def get_order(self, order_id: str) -> dict[str, Any]:
        order = self.s.orders.get(order_id)
        if order is None:
            raise OrderNotFoundError(f"order {order_id} not found")
        return order

    def mark_order_refunded(self, order_id: str, refund_id: str) -> dict[str, Any]:
        self.s.orders.mark_refunded(order_id, refund_id)
        return {"order_id": order_id, "status": "refunded", "refund_id": refund_id}


class CrmBackend:
    def __init__(self, s: Services):
        self.s = s

    def verify_customer(self, customer_id: str, email: str) -> bool:
        return self.s.customers.verify(customer_id, email)

    def add_case_note(self, customer_id: str, note: str) -> dict[str, Any]:
        self.s.crm.add_note(customer_id, note)
        return {"ok": True}


class PaymentsBackend:
    def __init__(self, s: Services):
        self.s = s

    def issue_refund(self, order_id: str, amount: float, key: str) -> dict[str, Any]:
        return self.s.refunds.issue(idempotency_key=key, order_id=order_id, amount=amount)


def build_gateway(services: Services) -> ToolGateway:
    conns = connect_backends(
        {
            "oms": OmsBackend(services),
            "crm": CrmBackend(services),
            "payments": PaymentsBackend(services),
        }
    )
    return ToolGateway(
        AGENT,
        IDENTITY,
        conns,
        ALLOW,
        schemas={"oms.get_order": Order},
        error_types={"OrderNotFoundError": OrderNotFoundError},
        quotas={"payments.issue_refund": 2},
        timeout_s=5.0,
    )
