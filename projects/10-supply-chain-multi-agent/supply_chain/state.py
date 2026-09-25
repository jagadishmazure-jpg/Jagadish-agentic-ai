"""Shared typed state, routing decision and output models."""

from __future__ import annotations

import operator
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field

AgentName = Literal["demand", "inventory", "supplier"]
NextAgent = Literal["demand", "inventory", "supplier", "FINISH"]
Outcome = Literal[
    "po_submitted",
    "no_reorder",
    "po_rejected",
    "review_failed",
    "no_supplier",
    "halted_budget",
    "sor_unavailable",
    "submit_failed",
]


class RouteDecision(BaseModel):
    """Structured output of the supervisor."""

    next_agent: NextAgent
    parallel: list[AgentName] = Field(
        default_factory=list, description="extra specialists to run concurrently with next_agent"
    )
    reason: str


class Recommendation(BaseModel):
    sku: str
    qty: int
    supplier: str
    unit_price: float
    lead_time_days: int
    total_cost: float
    draft_id: str
    need_qty: int
    # which agent/tool produced each number (provenance for the reviewer + humans)
    citations: dict[str, str]


class FinalReport(BaseModel):
    sku: str
    outcome: Outcome
    summary: str
    recommendation: Recommendation | None = None
    po_number: str | None = None
    review_issues: list[str] = Field(default_factory=list)
    agent_hops: int


def merge_dicts(left: dict | None, right: dict | None) -> dict:
    """Reducer: shallow-merge dict updates (lets parallel branches write disjoint keys)."""
    return {**(left or {}), **(right or {})}


class SupplyChainState(TypedDict, total=False):
    # input
    sku: str
    horizon_weeks: int
    # conversation between supervisor and specialists (summaries only)
    messages: Annotated[list[AnyMessage], add_messages]
    # structured slots filled by specialists; merged so parallel writers never clash
    slots: Annotated[dict[str, Any], merge_dicts]
    # control
    route: dict[str, Any]
    iterations: int
    cost_units: Annotated[int, operator.add]
    review: dict[str, Any] | None
    revisions: int
    approval: dict[str, Any] | None
    submission: dict[str, Any] | None
    outcome: Outcome
    # audit trail: one entry per agent hop / supervisor decision
    hops: Annotated[list[dict[str, Any]], operator.add]
    # five-exit trail: which non-success exit each node took (see doctrine.yaml)
    exits: Annotated[list[dict[str, str]], operator.add]
    final: dict[str, Any]
