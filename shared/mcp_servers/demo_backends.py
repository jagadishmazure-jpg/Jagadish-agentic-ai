"""Small seeded backends so every domain server can run standalone over stdio
(``python -m shared.mcp_servers <domain>``) for MCP Inspector / Claude Desktop / adapters."""

from typing import Any, ClassVar


class DemoOMS:
    orders: ClassVar[dict[str, dict[str, Any]]] = {
        "A-1001": {
            "order_id": "A-1001",
            "customer_id": "C-001",
            "total": 80.0,
            "status": "delivered",
            "delivered_on": "2026-09-10",
        }
    }

    def get_order(self, order_id: str) -> dict[str, Any]:
        if order_id not in self.orders:
            raise LookupError(f"order {order_id} not found")
        return self.orders[order_id]


class DemoTicketing:
    def __init__(self) -> None:
        self.tickets = {
            "T-1": {
                "ticket_id": "T-1",
                "account": "Contoso",
                "status": "open",
                "subject": "SSO login loop",
                "priority": "high",
            }
        }

    def list_tickets(self, account: str) -> list[dict[str, Any]]:
        return [t for t in self.tickets.values() if t["account"] == account]

    def get_ticket(self, ticket_id: str) -> dict[str, Any]:
        return self.tickets[ticket_id]

    def create_ticket(
        self, queue: str, subject: str, summary: str, priority: str, key: str
    ) -> dict[str, Any]:
        tid = f"T-{len(self.tickets) + 1}"
        self.tickets[tid] = {
            "ticket_id": tid,
            "queue": queue,
            "subject": subject,
            "summary": summary,
            "priority": priority,
            "status": "new",
            "account": "",
        }
        return self.tickets[tid]


class DemoERP:
    stock: ClassVar[dict[str, dict[str, Any]]] = {
        "SKU-1": {"sku": "SKU-1", "on_hand": 120, "safety_stock": 40, "lead_time_days": 7}
    }

    def get_stock(self, sku: str) -> dict[str, Any]:
        return self.stock[sku]


class DemoCRM:
    def get_interaction_history(self, account: str) -> list[dict[str, Any]]:
        return [{"id": "CRM-1", "date": "2026-09-01", "summary": f"QBR with {account}"}]


DEMO_BACKENDS = {"oms": DemoOMS, "ticketing": DemoTicketing, "erp": DemoERP, "crm": DemoCRM}
