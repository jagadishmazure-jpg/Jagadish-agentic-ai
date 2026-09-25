"""Mock payer/provider systems: member eligibility, PA portal (drafts, signed submission),
clinical notes, clinician registry, kill switches."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

MEMBERS = {
    "M-1001": {
        "name": "Jordan Blake",
        "dob": "1979-04-12",
        "mrn": "MRN-558812",
        "plan": "gold-ppo",
        "coverage_start": "2024-01-01",
        "coverage_end": "2026-12-31",
    },
    "M-2002": {
        "name": "Priya Nair",
        "dob": "1990-09-30",
        "mrn": "MRN-771203",
        "plan": "silver-hmo",
        "coverage_start": "2025-01-01",
        "coverage_end": "2026-12-31",
    },
    "M-3003": {
        "name": "Tom Reyes",
        "dob": "1965-02-01",
        "mrn": "MRN-310077",
        "plan": "gold-ppo",
        "coverage_start": "2023-01-01",
        "coverage_end": "2026-03-31",
    },
}
CLINICIANS = {"dr-osei": "MD", "np-lin": "NP"}

NOTE = (
    "Patient {name}, DOB: {dob}, {mrn}. Phone 512-555-0142, SSN 123-45-6789.\n"
    "Chief complaint: low back pain radiating to the left leg.\n{body}"
)


def note(member_id: str, body: str) -> str:
    m = MEMBERS[member_id]
    return NOTE.format(name=m["name"], dob=m["dob"], mrn=m["mrn"], body=body)


@dataclass
class Switches:
    """Runtime kill switches (App Configuration feature flags in Azure)."""

    coverage_language: bool = True

    def kill(self, name: str) -> None:
        setattr(self, name, False)


@dataclass
class Systems:
    drafts: dict[str, dict[str, Any]] = field(default_factory=dict)
    submissions: list[dict[str, Any]] = field(default_factory=list)
    switches: Switches = field(default_factory=Switches)

    def check_eligibility(self, member_id: str, dos: str) -> dict[str, Any]:
        m = MEMBERS[member_id]
        d = date.fromisoformat(dos)
        ok = date.fromisoformat(m["coverage_start"]) <= d <= date.fromisoformat(m["coverage_end"])
        return {"member_id": member_id, "eligible": ok, "plan": m["plan"], "plan_year": str(d.year)}

    def save_draft(self, packet: dict[str, Any]) -> dict[str, Any]:
        did = f"PA-D{len(self.drafts) + 1:04d}"
        self.drafts[did] = {**packet, "draft_id": did, "status": "draft"}
        return {"draft_id": did, "status": "draft"}

    def submit(self, draft_id: str, signed_by: str) -> dict[str, Any]:
        if signed_by not in CLINICIANS:
            raise PermissionError("submission requires a registered clinician signature")
        self.drafts[draft_id]["status"] = "submitted"
        ref = f"PA-{len(self.submissions) + 1:05d}"
        self.submissions.append({"ref": ref, "draft_id": draft_id, "signed_by": signed_by})
        return {"reference": ref, "status": "submitted"}

    def status(self, member_id: str) -> list[dict[str, Any]]:
        return [
            {"draft_id": d["draft_id"], "cpt": d["cpt"], "status": d["status"]}
            for d in self.drafts.values()
            if d["member_id"] == member_id
        ]


def seed_systems() -> Systems:
    return Systems()
