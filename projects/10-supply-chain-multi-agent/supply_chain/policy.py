"""Procurement policy and pure planning math (no I/O, no LLM)."""

from __future__ import annotations

import math
from typing import Any

MAX_LEAD_TIME_DAYS = 14
DEFAULT_HORIZON_WEEKS = 4
MAX_ITERATIONS = 8  # supervisor turns
MAX_COST_UNITS = 60  # LLM calls + tool calls across all agents
MAX_REVISIONS = 1  # reviewer can send the supplier agent back once

REQUIRED_CITATIONS = (
    "forecast_units",
    "on_hand",
    "open_po_qty",
    "safety_stock",
    "unit_price",
    "qty",
)


def need_qty(slots: dict[str, Any]) -> int | None:
    """Units to order = forecast - (on hand + open POs) + safety stock. None if unknown."""
    f, s = slots.get("forecast"), slots.get("stock")
    if not f or not s:
        return None
    raw = f["total_units"] - s["on_hand"] - s["open_po_qty"] + s["safety_stock"]
    return max(0, math.ceil(raw))


def acceptable_quotes(quotes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [q for q in quotes if q.get("available") and q["lead_time_days"] <= MAX_LEAD_TIME_DAYS]


def best_quote(quotes: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Cheapest quote whose lead time is acceptable."""
    ok = acceptable_quotes(quotes)
    return min(ok, key=lambda q: (q["unit_price"], q["lead_time_days"])) if ok else None
