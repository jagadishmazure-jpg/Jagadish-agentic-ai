"""MCP servers (tms, comms, claims) and gateways (reader, comms writer, claims writer)."""

from __future__ import annotations

from typing import Any

from exception_agent.systems import Systems
from shared.mcp_servers.kit import SorServer
from shared.resilience import Backoff
from shared.tools import ToolGateway, connect_servers

Json = dict[str, Any]


def servers(s: Systems) -> dict[str, SorServer]:
    tms = SorServer("tms", "Transportation management system.", "TMS")

    @tms.read
    def get_shipment(shipment_id: str, tenant: str) -> Json:
        """Shipment header (lane, carrier, promised date, TMS ETA) for the tenant."""
        return s.get_shipment(shipment_id, tenant)

    @tms.read
    def get_scan_events(shipment_id: str) -> Json:
        """Carrier scan / milestone events with source and confidence."""
        return s.get_scan_events(shipment_id)

    comms = SorServer("comms", "Customer communications (drafts for CS review).", "Comms")

    @comms.write
    def draft_notice(notice: Json, idempotency_key: str, dry_run: bool = True) -> Json:
        """Create a proactive delay notice draft."""
        return {"preview": notice} if dry_run else s.draft_notice(notice)

    claims = SorServer("claims", "Carrier claims management.", "Claims")

    @claims.write
    def create_claim_draft(claim: Json, idempotency_key: str, dry_run: bool = True) -> Json:
        """Create a carrier claim draft for a claims specialist to file."""
        return {"preview": claim} if dry_run else s.create_claim_draft(claim)

    @claims.write
    def queue_review(item: Json, idempotency_key: str, dry_run: bool = True) -> Json:
        """Queue a claim packet for manual review."""
        return {"preview": item} if dry_run else s.queue_review(item)

    return {"tms": tms, "comms": comms, "claims": claims}


def gateways(s: Systems) -> dict[str, ToolGateway]:
    conns = connect_servers(servers(s))
    kw = {
        "error_types": {"KeyError": KeyError},
        "retry": Backoff(attempts=2, base_s=0.05),
        "timeout_s": 5.0,
    }
    return {
        "reader": ToolGateway(
            "exception-agent",
            "mi-exception-reader",
            conns,
            {"tms.get_shipment", "tms.get_scan_events"},
            **kw,
        ),
        "comms": ToolGateway(
            "exception-agent", "mi-comms-writer", conns, {"comms.draft_notice"}, **kw
        ),
        "claims": ToolGateway(
            "exception-agent",
            "mi-claims-writer",
            conns,
            {"claims.create_claim_draft", "claims.queue_review"},
            **kw,
        ),
    }
