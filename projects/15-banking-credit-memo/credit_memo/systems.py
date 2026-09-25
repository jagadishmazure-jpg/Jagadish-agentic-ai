"""Mock bank systems: KYC screening, the existing PD/rating model, the loan system."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

APPROVERS = {
    "rm-diaz": "relationship_manager",
    "rm-kent": "relationship_manager",
    "co-nguyen": "credit_officer",
    "co-patel": "credit_officer",
}
SCREEN_HITS = {"Victor Sanz": "sanctions list: potential match (OFAC-style mock)"}
RISK = {
    "B-100": {"pd": 0.011, "grade": "BB+"},
    "B-200": {"pd": 0.02, "grade": "BB"},
    "B-300": {"pd": 0.015, "grade": "BB+"},
    "B-400": {"pd": 0.041, "grade": "B+"},
}
BORROWERS = {
    "B-100": "Northwind Fabrication LLC",
    "B-200": "Globex Tooling Inc",
    "B-300": "Initech Metals Corp",
    "B-400": "Contoso Castings LLC",
}


@dataclass
class Systems:
    limits: list[dict[str, Any]] = field(default_factory=list)

    def screen(self, names: list[str]) -> dict[str, Any]:
        return {
            "hits": {n: SCREEN_HITS[n] for n in names if n in SCREEN_HITS},
            "screened": names,
            "list_version": "2026-09-20",
        }

    def score(self, borrower_id: str) -> dict[str, Any]:
        return {**RISK[borrower_id], "model_version": "pd-scorecard-2026.03"}

    def set_credit_limit(
        self, borrower_id: str, amount: float, approvals: list[str]
    ) -> dict[str, Any]:
        """Server-side dual control: two distinct registered approvers, the second a credit
        officer. The graph checks this too; the system of record never trusts the caller."""
        if len(approvals) != 2 or len(set(approvals)) != 2:
            raise PermissionError("dual control: two distinct approvers required")
        if any(a not in APPROVERS for a in approvals):
            raise PermissionError("dual control: unregistered approver")
        if APPROVERS[approvals[1]] != "credit_officer":
            raise PermissionError("dual control: second approver must be a credit officer")
        ref = f"LIM-{len(self.limits) + 1:04d}"
        self.limits.append(
            {"ref": ref, "borrower_id": borrower_id, "amount": amount, "approvals": approvals}
        )
        return {"limit_ref": ref, "amount": amount}


def seed_systems() -> Systems:
    return Systems()
