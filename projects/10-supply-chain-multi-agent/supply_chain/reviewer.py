"""Critic: deterministic checks on the supplier agent's recommendation."""

from __future__ import annotations

from typing import Any

from supply_chain.policy import MAX_LEAD_TIME_DAYS, REQUIRED_CITATIONS, best_quote, need_qty

EXPECTED_AGENT = {
    "forecast_units": "demand_agent",
    "on_hand": "inventory_agent",
    "open_po_qty": "inventory_agent",
    "safety_stock": "inventory_agent",
    "unit_price": "supplier_agent",
    "qty": "supplier_agent",
}


def review(slots: dict[str, Any]) -> dict[str, Any]:
    rec = slots["recommendation"]
    need = need_qty(slots) or 0
    best = best_quote(slots.get("quotes", []))
    issues: list[str] = []

    if rec["qty"] < need:
        issues.append(
            f"qty {rec['qty']} does not cover need {need} "
            "(forecast - on hand - open POs + safety stock)"
        )
    if rec["lead_time_days"] > MAX_LEAD_TIME_DAYS:
        issues.append(f"lead time {rec['lead_time_days']}d exceeds {MAX_LEAD_TIME_DAYS}d")
    if best and rec["supplier"] != best["supplier"]:
        issues.append(
            f"{rec['supplier']} @ {rec['unit_price']:.2f} is not the cheapest acceptable quote; "
            f"use {best['supplier']} @ {best['unit_price']:.2f} ({best['lead_time_days']}d)"
        )
    for key in REQUIRED_CITATIONS:
        src = rec["citations"].get(key, "")
        if not src.startswith(EXPECTED_AGENT[key]):
            issues.append(f"citation for {key} missing or not from {EXPECTED_AGENT[key]}: {src!r}")

    return {
        "passed": not issues,
        "issues": issues,
        "expected_supplier": best["supplier"] if best else None,
        "draft_id": rec["draft_id"],
    }
