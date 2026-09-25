"""Mock systems: TMS (shipments + scan events), customer comms outbox, carrier claims."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

NOW = datetime(2026, 9, 25, 15, 0)

SHIPMENTS: dict[str, dict[str, Any]] = {
    "SH-1001": {
        "tenant": "northwind",
        "customer": "Acme Industrial",
        "lane": "CHI-NYC",
        "carrier": "Ridgeline Freight",
        "ship_date": "2026-09-23",
        "promised": "2026-09-26T17:00",
        "tms_eta": "2026-09-27T12:00",
        "status": "in_transit",
    },
    "SH-1002": {
        "tenant": "northwind",
        "customer": "Acme Industrial",
        "lane": "DAL-ATL",
        "carrier": "Coastal Carriers",
        "ship_date": "2026-09-23",
        "promised": "2026-09-25T17:00",
        "tms_eta": None,
        "status": "in_transit",
    },
    "SH-1003": {
        "tenant": "contoso",
        "customer": "Initech",
        "lane": "LAX-SEA",
        "carrier": "Ridgeline Freight",
        "ship_date": "2026-09-10",
        "promised": "2026-09-14T17:00",
        "tms_eta": None,
        "status": "delivered",
    },
    "SH-1004": {
        "tenant": "northwind",
        "customer": "Globex Retail",
        "lane": "CHI-NYC",
        "carrier": "Ridgeline Freight",
        "ship_date": "2026-09-24",
        "promised": "2026-09-27T17:00",
        "tms_eta": "2026-09-27T10:00",
        "status": "in_transit",
    },
    "SH-1005": {
        "tenant": "contoso",
        "customer": "Initech",
        "lane": "LAX-SEA",
        "carrier": "Ridgeline Freight",
        "ship_date": "2026-02-26",
        "promised": "2026-03-02T17:00",
        "tms_eta": None,
        "status": "delivered",
    },
}


def _ev(
    eid: str,
    ts: str,
    loc: str,
    code: str,
    source: str = "edi",
    conf: float = 0.97,
    remark: str = "",
) -> dict[str, Any]:
    return {
        "event_id": eid,
        "ts": ts,
        "location": loc,
        "code": code,
        "source": source,
        "confidence": conf,
        "remark": remark,
    }


SCANS: dict[str, list[dict[str, Any]]] = {
    "SH-1001": [
        _ev("EV-1001-1", "2026-09-23T08:10", "Chicago IL terminal", "picked_up"),
        _ev("EV-1001-2", "2026-09-24T21:40", "Toledo OH hub", "departed_hub"),
        _ev(
            "EV-1001-3",
            "2026-09-25T14:30",
            "Cleveland OH hub",
            "arrived_hub",
            remark="arrived 5.5 h after plan",
        ),
    ],
    "SH-1002": [
        _ev("EV-1002-1", "2026-09-23T07:00", "Dallas TX terminal", "picked_up"),
        _ev(
            "EV-1002-2", "2026-09-24T19:00", "Shreveport LA hub", "departed_hub", "driver_app", 0.9
        ),
    ],
    "SH-1003": [
        _ev("EV-1003-1", "2026-09-10T09:00", "Los Angeles CA terminal", "picked_up"),
        _ev(
            "EV-1003-2",
            "2026-09-14T11:20",
            "Seattle WA consignee",
            "delivered",
            remark="POD exception: 2 pallets crushed",
        ),
    ],
    "SH-1004": [
        _ev("EV-1004-1", "2026-09-24T09:00", "Chicago IL terminal", "picked_up"),
        _ev("EV-1004-2", "2026-09-25T12:15", "Toledo OH hub", "arrived_hub"),
    ],
    "SH-1005": [
        _ev(
            "EV-1005-1",
            "2026-03-02T10:00",
            "Seattle WA consignee",
            "delivered",
            remark="POD exception: carton torn",
        ),
    ],
}
LOCATIONS = sorted(
    {e["location"] for evs in SCANS.values() for e in evs}
    | {"Columbus OH", "Pittsburgh PA", "Buffalo NY", "Memphis TN", "Birmingham AL", "Jackson MS"}
)


@dataclass
class Systems:
    shipments: dict[str, dict[str, Any]]
    scans: dict[str, list[dict[str, Any]]]
    now: datetime = NOW
    notices: list[dict[str, Any]] = field(default_factory=list)
    claims: list[dict[str, Any]] = field(default_factory=list)
    review_queue: list[dict[str, Any]] = field(default_factory=list)

    def get_shipment(self, shipment_id: str, tenant: str) -> dict[str, Any]:
        s = self.shipments[shipment_id]
        if s["tenant"] != tenant:  # tenant isolation in the SoR
            raise KeyError(shipment_id)
        return {"shipment_id": shipment_id, **s}

    def get_scan_events(self, shipment_id: str) -> dict[str, Any]:
        return {"events": list(self.scans.get(shipment_id, [])), "as_of": self.now.isoformat()}

    def draft_notice(self, notice: dict[str, Any]) -> dict[str, Any]:
        ref = f"NT-{len(self.notices) + 1:04d}"
        self.notices.append({"ref": ref, "status": "draft", **notice})
        return {"notice_ref": ref, "status": "draft"}

    def create_claim_draft(self, claim: dict[str, Any]) -> dict[str, Any]:
        ref = f"CC-{len(self.claims) + 1:04d}"
        self.claims.append({"ref": ref, "status": "draft", **claim})
        return {"claim_ref": ref, "status": "draft"}

    def queue_review(self, item: dict[str, Any]) -> dict[str, Any]:
        ref = f"RV-{len(self.review_queue) + 1:04d}"
        self.review_queue.append({"ref": ref, **item})
        return {"queue_ref": ref}


def seed_systems() -> Systems:
    return Systems(copy.deepcopy(SHIPMENTS), copy.deepcopy(SCANS))
