"""CRM (interaction history, open deals) and the support desk (tickets) behind MCP.

The graph reaches them only through a ToolGateway with the meeting-prep identity and a
read-only allowlist; payloads are schema-validated and sanitised (tool output is untrusted).
News is public web content and stays a direct fetcher.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict

from meeting_prep.sources import CRM, DEALS, TICKETS, Sources
from shared.tools import ToolGateway, connect_backends

AGENT = "meeting-prep"
IDENTITY = "mi-meeting-prep"
ALLOW = {"crm.get_interaction_history", "crm.get_open_deals", "ticketing.list_tickets"}


class _Item(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str


class Interaction(_Item):
    date: str
    type: str
    note: str


class Deal(_Item):
    name: str
    amount: int | float
    stage: str
    close: str


class Ticket(_Item):
    priority: str
    status: str
    subject: str


class CrmBackend:
    def __init__(self, s: Sources):
        self.s = s

    def get_interaction_history(self, account: str) -> list[dict[str, Any]]:
        return self.s._fetch("crm", CRM, account)

    def get_open_deals(self, account: str) -> list[dict[str, Any]]:
        return self.s._fetch("deals", DEALS, account)


class SupportBackend:
    def __init__(self, s: Sources):
        self.s = s

    def list_tickets(self, account: str) -> list[dict[str, Any]]:
        return self.s._fetch("support", TICKETS, account)


def build_gateway(sources: Sources) -> ToolGateway:
    return ToolGateway(
        AGENT,
        IDENTITY,
        connect_backends({"crm": CrmBackend(sources), "ticketing": SupportBackend(sources)}),
        ALLOW,
        schemas={
            "crm.get_interaction_history": list[Interaction],
            "crm.get_open_deals": list[Deal],
            "ticketing.list_tickets": list[Ticket],
        },
        timeout_s=5.0,
        retry=None,  # the research node owns the single transient retry
        breaker_threshold=5,
    )
