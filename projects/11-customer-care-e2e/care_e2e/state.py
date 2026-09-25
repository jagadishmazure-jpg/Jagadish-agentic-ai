"""Typed state for the care graph."""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class CareRequest(TypedDict):
    request_id: str
    channel: str  # web | app | email
    tenant: str
    customer_id: str
    email: str
    message: str


class CareState(TypedDict, total=False):
    request: CareRequest
    intent: dict[str, Any]
    fraud: bool
    route: str  # plan | fraud | clarify | human
    plan: dict[str, Any]
    order: dict[str, Any] | None
    policy: dict[str, Any]  # {chunk_ids, edition, degraded}
    history: list[dict[str, Any]]  # visible, sanitised case snippets
    injection: bool
    proposal: dict[str, Any] | None
    facts: dict[str, Any]
    draft: str
    critic: dict[str, Any]
    needs_human: list[str]  # reasons
    approval: dict[str, Any] | None
    outcome: str
    reply: str
    ticket: str | None
    citations: Annotated[list[str], operator.add]
    tool_calls: Annotated[int, operator.add]
    exits: Annotated[list[dict[str, str]], operator.add]
    trace: Annotated[list[str], operator.add]
