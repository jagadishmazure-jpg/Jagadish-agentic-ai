"""Deterministic criteria per (CPT, plan year) + plan rules, and fact extraction from the note.

Each criterion names the policy document it comes from; the graph only evaluates criteria
whose policy was actually retrieved for this member's plan and date of service."""

from __future__ import annotations

import re
from typing import Any

RED_FLAGS = re.compile(
    r"foot drop|saddle an(a)?esthesia|progressive (neurological )?deficit|"
    r"cauda equina|history of cancer|fever with",
    re.I,
)


def extract_facts(note: str) -> dict[str, Any]:
    weeks = re.search(r"(\d+)\s+weeks? of (?:physical therapy|conservative|pt\b)", note, re.I)
    no_flags = re.search(r"no red flags", note, re.I)
    return {
        "conservative_weeks": int(weeks.group(1)) if weeks else 0,
        "red_flags": bool(RED_FLAGS.search(note)) and not no_flags,
        "referral_on_file": bool(re.search(r"referral (is )?on file", note, re.I)),
        "mechanical_symptoms": bool(re.search(r"locking|catching", note, re.I)),
    }


CRITERIA = {
    ("72148", "2025"): ("MP-LSPINE-MRI-2025", 6),
    ("72148", "2026"): ("MP-LSPINE-MRI-2026", 4),
    ("29881", "2026"): ("MP-KNEE-SCOPE-2026", 6),
}
ADVANCED_IMAGING = {"72148"}


def evaluate(cpt: str, plan: str, plan_year: str, f: dict[str, Any]) -> dict[str, Any]:
    if (cpt, plan_year) not in CRITERIA:
        return {
            "status": "unknown",
            "policies": [],
            "met": [],
            "unmet": [f"no policy for CPT {cpt} in plan year {plan_year}"],
        }
    doc, weeks = CRITERIA[(cpt, plan_year)]
    met, unmet, policies = [], [], [doc]
    if cpt == "29881":
        (met if f["mechanical_symptoms"] else unmet).append("mechanical symptoms")
        (met if f["conservative_weeks"] >= weeks else unmet).append(
            f">= {weeks} weeks conservative therapy (documented {f['conservative_weeks']})"
        )
    elif f["red_flags"]:
        met.append("red flags present")
    else:
        (met if f["conservative_weeks"] >= weeks else unmet).append(
            f">= {weeks} weeks conservative therapy (documented {f['conservative_weeks']})"
        )
    if plan == "silver-hmo" and cpt in ADVANCED_IMAGING and plan_year == "2026":
        policies.append("MP-SILVER-REFERRAL-2026")
        (met if f["referral_on_file"] else unmet).append("PCP referral on file")
    return {
        "status": "criteria_met" if not unmet else "criteria_not_met",
        "policies": policies,
        "met": met,
        "unmet": unmet,
    }
