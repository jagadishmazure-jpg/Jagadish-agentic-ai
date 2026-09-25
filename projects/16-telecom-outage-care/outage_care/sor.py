"""MCP servers (OSS, billing, diagnostics, offers, field service) and gateway identities.

* ``mi-care-reader``: oss, billing, diagnostics, offers (read)
* ``mi-field-writer``: field.create_dispatch (write, idempotent)
* ``mi-noc-reader``: oss.get_active_incidents only - the NOC assistant summarises, it cannot act
"""

from __future__ import annotations

from typing import Any

from outage_care.systems import Systems
from shared.mcp_servers.kit import SorServer
from shared.resilience import Backoff
from shared.tools import ToolGateway, connect_servers

Json = dict[str, Any]


def servers(s: Systems) -> dict[str, SorServer]:
    oss = SorServer("oss", "Network OSS / fault management.", "OSS")

    @oss.read
    def get_active_incidents() -> Json:
        """Active network incidents with the feed's last observation time."""
        return s.active_incidents()

    billing = SorServer("billing", "Billing system.", "Billing")

    @billing.read
    def get_bill(account: str) -> Json:
        """Latest bill with line items."""
        return s.bills[account]

    diag = SorServer("diagnostics", "Line diagnostics.", "Diagnostics")

    @diag.read
    def line_test(account: str) -> Json:
        """Remote line test (ONT status, optical signal)."""
        return s.line_test(account)

    offers = SorServer("offers", "Offer engine.", "Offers")

    @offers.read
    def get_offers(account: str) -> list[Json]:
        """Eligible offers for the account."""
        return s.offers(account)

    fieldsvc = SorServer("field", "Field service management.", "Field service")

    @fieldsvc.write
    def create_dispatch(pack: Json, idempotency_key: str, dry_run: bool = True) -> Json:
        """Create a technician dispatch with its context pack."""
        return {"preview": pack} if dry_run else s.create_dispatch(pack)

    return {
        "oss": oss,
        "billing": billing,
        "diagnostics": diag,
        "offers": offers,
        "field": fieldsvc,
    }


def gateways(s: Systems) -> dict[str, ToolGateway]:
    conns = connect_servers(servers(s))
    kw = {
        "error_types": {"KeyError": KeyError},
        "retry": Backoff(attempts=2, base_s=0.05),
        "timeout_s": 5.0,
    }
    return {
        "care": ToolGateway(
            "outage-care",
            "mi-care-reader",
            conns,
            {
                "oss.get_active_incidents",
                "billing.get_bill",
                "diagnostics.line_test",
                "offers.get_offers",
            },
            **kw,
        ),
        "field": ToolGateway(
            "outage-care", "mi-field-writer", conns, {"field.create_dispatch"}, **kw
        ),
        "noc": ToolGateway(
            "noc-assistant", "mi-noc-reader", conns, {"oss.get_active_incidents"}, **kw
        ),
    }
