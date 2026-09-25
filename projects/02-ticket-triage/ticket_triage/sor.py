"""Ticketing system of record behind MCP. Triage only *creates* tickets (idempotent by the
inbound ticket id) and only ever sends redacted text - the PII vault never leaves the node."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from shared.tools import ToolGateway, connect_backends

AGENT = "ticket-triage"
IDENTITY = "mi-ticket-triage"
ALLOW = {"ticketing.create_ticket"}


class CreatedTicket(BaseModel):
    """Contract for ticketing.create_ticket payloads (tool output is untrusted)."""

    model_config = ConfigDict(extra="allow")
    ticket_id: str
    queue: str
    status: str


class TicketingBackend:
    """In-memory service desk (ServiceNow/Zendesk-like)."""

    def __init__(self) -> None:
        self.tickets: dict[str, dict[str, Any]] = {}

    def create_ticket(
        self, queue: str, subject: str, summary: str, priority: str, key: str
    ) -> dict[str, Any]:
        tid = f"SD-{len(self.tickets) + 1:04d}"
        self.tickets[tid] = {
            "ticket_id": tid,
            "queue": queue,
            "subject": subject,
            "summary": summary,
            "priority": priority,
            "status": "new",
            "idempotency_key": key,
        }
        return self.tickets[tid]


def build_gateway(backend: TicketingBackend) -> ToolGateway:
    return ToolGateway(
        AGENT,
        IDENTITY,
        connect_backends({"ticketing": backend}),
        ALLOW,
        schemas={"ticketing.create_ticket": CreatedTicket},
        timeout_s=5.0,
    )
