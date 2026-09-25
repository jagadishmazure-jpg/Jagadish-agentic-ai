"""Deterministic coverage + payable rules per form edition and jurisdiction.

The model never decides coverage or amounts. Each rule names the provision (doc id) it rests
on; the graph only accepts the decision if that provision was actually retrieved for this
policy's edition and state (grounding check)."""

from __future__ import annotations

from typing import Any

SEEPAGE_DAYS_EXCLUDED = {"2019": 30, "2023": 14}
MOLD_SUBLIMIT = {
    ("TX", "2019"): (5000, "TX-AMEND-2019-MOLD"),
    ("TX", "2023"): (8000, "TX-AMEND-2023-MOLD"),
    ("CA", "2023"): (10000, "CA-AMEND-2023-MOLD"),
}
PERILS = {"fire", "wind", "theft"}


def coverage(
    cause: str, edition: str, state: str, seepage_days: int, mold_amount: float
) -> dict[str, Any]:
    if cause == "flood":
        return {
            "status": "excluded",
            "provisions": ["HO3-FLOOD"],
            "reason": "flood and surface water are excluded",
        }
    if cause == "water":
        limit = SEEPAGE_DAYS_EXCLUDED[edition]
        water = f"HO3-{edition}-WATER"
        if seepage_days >= limit:
            return {
                "status": "excluded",
                "provisions": [water],
                "reason": f"continuous or repeated seepage over {limit} days or more is "
                f"excluded under the {edition} edition",
            }
        out = {
            "status": "covered",
            "provisions": [water],
            "reason": "sudden and accidental discharge of water is covered",
        }
        if mold_amount:
            sub, doc = MOLD_SUBLIMIT[(state, edition)]
            out |= {"mold_sublimit": sub, "provisions": [water, doc]}
        return out
    if cause in PERILS:
        return {
            "status": "covered",
            "provisions": [f"HO3-{edition}-PERILS"],
            "reason": f"{cause} is a covered peril",
        }
    return {"status": "unknown", "provisions": [], "reason": f"cause '{cause}' needs an adjuster"}


def payable(
    estimate: float, mold_amount: float, cov: dict[str, Any], policy: dict[str, Any]
) -> dict[str, float]:
    if cov["status"] != "covered":
        return {"gross": 0.0, "payable": 0.0}
    mold = min(mold_amount, cov.get("mold_sublimit", mold_amount))
    gross = min(estimate - mold_amount + mold, policy["dwelling_limit"])
    return {
        "gross": round(gross, 2),
        "payable": round(max(0.0, gross - policy["deductible"]), 2),
        "capped_at_limit": estimate - mold_amount + mold > policy["dwelling_limit"],
    }
