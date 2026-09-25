"""Mock dealer systems: VIN decode, parts ATP (with part supersession), warranty."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

VEHICLES = {
    "VIN-X5-22-0001": {
        "model": "Arden X5",
        "year": 2022,
        "engine": "2.0T",
        "build_date": "2022-03-10",
        "in_service": "2022-05-01",
        "miles": 41000,
    },
    "VIN-X5-21-0002": {
        "model": "Arden X5",
        "year": 2021,
        "engine": "2.0T",
        "build_date": "2021-06-02",
        "in_service": "2021-08-15",
        "miles": 30500,
    },
    "VIN-X5-23-0003": {
        "model": "Arden X5",
        "year": 2023,
        "engine": "2.0T",
        "build_date": "2023-01-20",
        "in_service": "2023-03-01",
        "miles": 72000,
    },
    "VIN-C3-24-0004": {
        "model": "Arden C3",
        "year": 2024,
        "engine": "EV",
        "build_date": "2024-01-05",
        "in_service": "2024-02-20",
        "miles": 9000,
    },
}
PARTS = {
    "11-4455-A": {"superseded_by": "11-4455-C"},
    "11-4455-C": {"on_hand": 2},
    "11-4460-B": {"on_hand": 0, "eta_days": 2},
    "33-1200-D": {"on_hand": 1},
    "77-0901-A": {"on_hand": 1},
}
PROGRAMS = {  # op code -> (program, years, miles)
    "COOL-PUMP-R": ("powertrain", 5, 60000),
    "INFO-SW-UPD": ("basic", 3, 36000),
    "CHG-DOOR-R": ("basic", 3, 36000),
    "WIN-REG-R": ("basic", 3, 36000),
}


@dataclass
class Systems:
    claims: list[dict[str, Any]] = field(default_factory=list)

    def decode_vin(self, vin: str) -> dict[str, Any]:
        return {"vin": vin, **VEHICLES[vin]}

    def check_atp(self, part_number: str, dealer: str) -> dict[str, Any]:
        p = PARTS[part_number]
        if "superseded_by" in p:
            return {"part_number": part_number, "superseded_by": p["superseded_by"]}
        return {
            "part_number": part_number,
            "on_hand": p["on_hand"],
            "eta_days": p.get("eta_days", 0),
            "dealer": dealer,
        }

    def check_coverage(self, vin: str, op_code: str, repair_date: str) -> dict[str, Any]:
        v = VEHICLES[vin]
        program, years, miles = PROGRAMS[op_code]
        age = (date.fromisoformat(repair_date) - date.fromisoformat(v["in_service"])).days
        ok_time, ok_miles = age <= years * 365, v["miles"] <= miles
        reason = (
            "within limits"
            if ok_time and ok_miles
            else (f"exceeds {miles:,} miles" if not ok_miles else f"exceeds {years} years")
        )
        return {
            "covered": ok_time and ok_miles,
            "program": f"{program} {years}y/{miles // 1000}k",
            "reason": reason,
        }

    def submit_claim(self, claim: dict[str, Any]) -> dict[str, Any]:
        ref = f"WC-{len(self.claims) + 1:05d}"
        self.claims.append({"ref": ref, **claim})
        return {"claim_ref": ref}


def seed_systems() -> Systems:
    return Systems()
