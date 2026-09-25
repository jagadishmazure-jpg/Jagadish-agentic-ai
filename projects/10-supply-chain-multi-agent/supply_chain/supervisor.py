"""Supervisor: an LLM proposes the next hop as structured output; deterministic guards
validate it against state (prerequisites, schema) and fall back to the plan policy."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import ValidationError

from supply_chain.policy import need_qty
from supply_chain.state import RouteDecision

SUPERVISOR_SYSTEM = """TASK: ROUTE
You are the supervisor of a replenishment team: demand (forecast), inventory (stock, open POs,
safety stock) and supplier (quotes, draft PO). Given the JSON status, choose who runs next.
Rules: demand and inventory are independent and may run in parallel; supplier needs both a
forecast and stock and only runs when need_qty > 0; FINISH when need_qty == 0, when a
recommendation exists, or when sourcing failed.
Reply ONLY with JSON: {"next_agent": "demand|inventory|supplier|FINISH",
"parallel": ["inventory"], "reason": "..."}"""


def status(state: dict[str, Any]) -> dict[str, Any]:
    """Compact view the supervisor LLM sees (no raw data, just what it needs to route)."""
    slots = state.get("slots", {})
    return {
        "sku": state["sku"],
        "has_forecast": bool(slots.get("forecast")),
        "has_stock": bool(slots.get("stock")),
        "need_qty": need_qty(slots),
        "has_recommendation": bool(slots.get("recommendation")),
        "sourcing_failed": bool(slots.get("sourcing_failed")),
    }


def plan_next(s: dict[str, Any]) -> RouteDecision:
    """Deterministic routing policy (used by the mock LLM and as the guard fallback)."""
    if not s["has_forecast"] and not s["has_stock"]:
        return RouteDecision(
            next_agent="demand",
            parallel=["inventory"],
            reason="forecast and stock are independent: fan out in parallel",
        )
    if not s["has_forecast"]:
        return RouteDecision(next_agent="demand", reason="forecast missing")
    if not s["has_stock"]:
        return RouteDecision(next_agent="inventory", reason="stock position missing")
    if s["need_qty"] == 0:
        return RouteDecision(next_agent="FINISH", reason="stock covers forecast + safety stock")
    if s["has_recommendation"] or s["sourcing_failed"]:
        return RouteDecision(next_agent="FINISH", reason="sourcing complete: send to reviewer")
    return RouteDecision(next_agent="supplier", reason=f"need {s['need_qty']} units: source it")


def validate(d: RouteDecision, s: dict[str, Any]) -> str | None:
    """Return a violation message, or None if the proposal is allowed."""
    if d.next_agent == "supplier" and not (s["has_forecast"] and s["has_stock"]):
        return "supplier requires forecast and stock"
    if d.next_agent == "supplier" and s["need_qty"] == 0:
        return "no reorder needed"
    if d.next_agent == "FINISH" and not (
        s["need_qty"] == 0 or s["has_recommendation"] or s["sourcing_failed"]
    ):
        return "cannot finish before the plan is complete"
    if any(p not in ("demand", "inventory") or p == d.next_agent for p in d.parallel):
        return "only demand/inventory may run in parallel"
    return None


def mock_supervisor(msgs: Sequence[BaseMessage]) -> str:
    return plan_next(json.loads(str(msgs[-1].content))).model_dump_json()


def decide(llm: BaseChatModel, state: dict[str, Any]) -> tuple[RouteDecision, bool]:
    """Ask the LLM, then guard. Returns (decision, overridden)."""
    s = status(state)
    raw = str(llm.invoke([SystemMessage(SUPERVISOR_SYSTEM), HumanMessage(json.dumps(s))]).content)
    match = re.search(r"\{.*\}", raw, re.S)
    try:
        proposal = RouteDecision.model_validate_json(match.group(0) if match else raw)
    except ValidationError:
        fb = plan_next(s)
        return fb.model_copy(update={"reason": f"guard: unparseable LLM output; {fb.reason}"}), True
    violation = validate(proposal, s)
    if violation:
        fb = plan_next(s)
        return fb.model_copy(update={"reason": f"guard override ({violation}); {fb.reason}"}), True
    return proposal, False
