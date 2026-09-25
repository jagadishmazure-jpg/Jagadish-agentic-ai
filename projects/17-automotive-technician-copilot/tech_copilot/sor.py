"""MCP servers (vehicle, parts, warranty) and gateways (reader, warranty writer)."""

from __future__ import annotations

from typing import Any

from shared.mcp_servers.kit import SorServer
from shared.resilience import Backoff
from shared.tools import ToolGateway, connect_servers
from tech_copilot.systems import Systems

Json = dict[str, Any]


def servers(s: Systems) -> dict[str, SorServer]:
    veh = SorServer("vehicle", "Vehicle master / VIN decode.", "Vehicle master")

    @veh.read
    def decode_vin(vin: str) -> Json:
        """Model, year, engine, build date, in-service date, mileage."""
        return s.decode_vin(vin)

    parts = SorServer("parts", "Dealer parts inventory (DMS).", "Parts / DMS")

    @parts.read
    def check_atp(part_number: str, dealer: str) -> Json:
        """Available-to-promise for a part at a dealer (reports part supersession)."""
        return s.check_atp(part_number, dealer)

    wty = SorServer("warranty", "OEM warranty system.", "Warranty")

    @wty.read
    def check_coverage(vin: str, op_code: str, repair_date: str) -> Json:
        """Coverage program and limits for an operation on this VIN."""
        return s.check_coverage(vin, op_code, repair_date)

    @wty.write
    def submit_claim(claim: Json, idempotency_key: str, dry_run: bool = True) -> Json:
        """Submit a warranty claim (requires a warranty administrator approval)."""
        return {"preview": claim} if dry_run else s.submit_claim(claim)

    return {"vehicle": veh, "parts": parts, "warranty": wty}


def gateways(s: Systems) -> dict[str, ToolGateway]:
    conns = connect_servers(servers(s))
    kw = {
        "error_types": {"KeyError": KeyError},
        "retry": Backoff(attempts=2, base_s=0.05),
        "timeout_s": 5.0,
    }
    return {
        "reader": ToolGateway(
            "tech-copilot",
            "mi-tech-reader",
            conns,
            {"vehicle.decode_vin", "parts.check_atp", "warranty.check_coverage"},
            **kw,
        ),
        "claims": ToolGateway(
            "tech-copilot", "mi-warranty-writer", conns, {"warranty.submit_claim"}, **kw
        ),
    }
