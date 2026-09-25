"""MCP servers (eligibility API, PA portal) and three gateway identities.

* ``mi-pa-reader``: eligibility.check_eligibility, pa_portal.get_status
* ``mi-pa-drafter``: pa_portal.save_draft (the agent can only ever draft)
* ``mi-pa-submitter``: pa_portal.submit - used only after clinician sign-off, and the portal
  itself rejects a submission without a registered clinician signature.
"""

from __future__ import annotations

from typing import Any

from prior_auth.systems import Systems
from shared.mcp_servers.kit import SorServer
from shared.resilience import Backoff
from shared.tools import ToolGateway, connect_servers

Json = dict[str, Any]


def servers(s: Systems) -> dict[str, SorServer]:
    elig = SorServer("eligibility", "Payer eligibility API (X12 270/271 style).", "Eligibility")

    @elig.read
    def check_eligibility(member_id: str, dos: str) -> Json:
        """Is the member covered on the date of service, and on which plan."""
        return s.check_eligibility(member_id, dos)

    pa = SorServer("pa_portal", "Prior authorization portal.", "PA portal")

    @pa.write
    def save_draft(packet: Json, idempotency_key: str, dry_run: bool = True) -> Json:
        """Save a prior-auth packet as a DRAFT (never submits)."""
        return {"preview": packet} if dry_run else s.save_draft(packet)

    @pa.write
    def submit(draft_id: str, signed_by: str, idempotency_key: str, dry_run: bool = True) -> Json:
        """Submit a draft; requires a registered clinician signature."""
        return {"preview": draft_id} if dry_run else s.submit(draft_id, signed_by)

    @pa.read
    def get_status(member_id: str) -> list[Json]:
        """Status of a member's prior-auth requests (no clinical content)."""
        return s.status(member_id)

    return {"eligibility": elig, "pa_portal": pa}


def gateways(s: Systems) -> dict[str, ToolGateway]:
    conns = connect_servers(servers(s))
    kw = {
        "error_types": {"KeyError": KeyError, "PermissionError": PermissionError},
        "retry": Backoff(attempts=2, base_s=0.05),
        "timeout_s": 5.0,
    }
    return {
        "reader": ToolGateway(
            "pa-graph",
            "mi-pa-reader",
            conns,
            {"eligibility.check_eligibility", "pa_portal.get_status"},
            **kw,
        ),
        "drafter": ToolGateway("pa-graph", "mi-pa-drafter", conns, {"pa_portal.save_draft"}, **kw),
        "submitter": ToolGateway("pa-graph", "mi-pa-submitter", conns, {"pa_portal.submit"}, **kw),
    }
