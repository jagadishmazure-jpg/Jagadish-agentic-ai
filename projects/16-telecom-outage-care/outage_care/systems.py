"""Mock OSS (incidents with observation time), billing, diagnostics, offers, field service."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

NOW = datetime(2026, 9, 25, 14, 0)
ACCOUNTS = {
    "A-100": {
        "name": "Dana Cho",
        "plan": "Fiber 500",
        "address": "18 Pine Ave",
        "equipment": "ONT-G2 + WiFi6 router",
    },
    "A-200": {
        "name": "Eli Ford",
        "plan": "Fiber 500",
        "address": "7 Lake Rd",
        "equipment": "ONT-G2",
    },
    "A-300": {
        "name": "Fay Singh",
        "plan": "Mobile Unlimited",
        "address": "3 Hill St",
        "equipment": "handset",
    },
    "A-400": {
        "name": "Gus Ward",
        "plan": "Fiber 500",
        "address": "91 Oak Ct",
        "equipment": "ONT-G1 (legacy)",
    },
}
BILLS = {
    "A-100": {
        "period_start": "2026-09-01",
        "total": 87.5,
        "lines": [
            {"code": "PLAN", "description": "Fiber 500 monthly", "amount": 65.0},
            {
                "code": "PRORATION",
                "description": "Upgrade from Fiber 300 on Sep 12, partial month",
                "amount": 12.5,
            },
            {"code": "EQUIP", "description": "WiFi6 router rental", "amount": 10.0},
        ],
    },
    "A-200": {
        "period_start": "2026-09-01",
        "total": 65.0,
        "lines": [{"code": "PLAN", "description": "Fiber 500 monthly", "amount": 65.0}],
    },
    "A-300": {
        "period_start": "2026-09-01",
        "total": 55.0,
        "lines": [{"code": "PLAN", "description": "Mobile Unlimited monthly", "amount": 55.0}],
    },
    "A-400": {
        "period_start": "2025-11-01",
        "total": 60.0,
        "lines": [{"code": "PLAN", "description": "Fiber 500 monthly", "amount": 60.0}],
    },
}
LINE_TARIFF = {"PRORATION": "TAR-PRORATION-1", "EQUIP": "TAR-EQUIP-1"}


@dataclass
class Systems:
    now: datetime = NOW
    oss_lag_min: int = 5  # how old the OSS feed's last observation is
    incidents: list[dict[str, Any]] = field(
        default_factory=lambda: [
            {
                "id": "INC-1",
                "node": "AGG-2",
                "state": "confirmed",
                "cause": "fiber cut (backhoe)",
                "started": (NOW - timedelta(hours=1)).isoformat(),
                "eta": (NOW + timedelta(hours=2)).isoformat(),
            }
        ]
    )
    ont_offline: set[str] = field(default_factory=lambda: {"A-400"})
    dispatches: list[dict[str, Any]] = field(default_factory=list)
    bills: dict[str, dict[str, Any]] = field(
        default_factory=lambda: {
            k: {**v, "lines": [dict(x) for x in v["lines"]]} for k, v in BILLS.items()
        }
    )

    def active_incidents(self) -> dict[str, Any]:
        return {
            "incidents": self.incidents,
            "observed_at": (self.now - timedelta(minutes=self.oss_lag_min)).isoformat(),
        }

    def line_test(self, account: str) -> dict[str, Any]:
        off = account in self.ont_offline
        return {
            "account": account,
            "ont": "offline" if off else "online",
            "signal_dbm": None if off else -19.5,
        }

    def offers(self, account: str) -> list[dict[str, Any]]:
        return [{"offer_id": "OF-GIG", "text": "Upgrade to Fiber 1 Gig for $15 more per month"}]

    def create_dispatch(self, pack: dict[str, Any]) -> dict[str, Any]:
        ref = f"FS-{len(self.dispatches) + 1:04d}"
        self.dispatches.append({"ref": ref, **pack})
        return {"dispatch_ref": ref, "window": "tomorrow 08:00-12:00"}


def seed_systems(**kw: Any) -> Systems:
    return Systems(**kw)
