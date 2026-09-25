"""Hard stop conditions for the autonomous loop, implemented as create_agent middleware.

- max_steps:      model turns per investigation
- max_tool_cost:  sum of TOOL_COST of executed tools
- loop detection: identical tool + args requested again -> tool is NOT executed; after
                  ``max_loop_hits`` such attempts the agent is stopped
"""

from __future__ import annotations

import json
from typing import Any

from langchain.agents.middleware import AgentMiddleware, hook_config
from langchain_core.messages import AIMessage, ToolMessage

from incident_agent.tools import TOOL_COST

LOOP_PREFIX = "LOOP DETECTED"
BUDGET_PREFIX = "BUDGET EXCEEDED"
STOP_PREFIX = "STOPPED:"


def _executed(msgs: list[Any]) -> list[ToolMessage]:
    return [
        m
        for m in msgs
        if isinstance(m, ToolMessage)
        and not str(m.content).startswith((LOOP_PREFIX, BUDGET_PREFIX))
    ]


def spent(msgs: list[Any]) -> int:
    return sum(TOOL_COST.get(m.name or "", 0) for m in _executed(msgs))


class GuardrailMiddleware(AgentMiddleware):
    def __init__(self, max_steps: int = 8, max_tool_cost: int = 20, max_loop_hits: int = 2):
        super().__init__()
        self.max_steps, self.max_tool_cost, self.max_loop_hits = (
            max_steps,
            max_tool_cost,
            max_loop_hits,
        )

    @hook_config(can_jump_to=["end"])
    def before_model(self, state: dict[str, Any], runtime: Any) -> dict[str, Any] | None:
        msgs = state["messages"]
        steps = sum(isinstance(m, AIMessage) for m in msgs)
        cost = spent(msgs)
        loops = sum(
            isinstance(m, ToolMessage) and str(m.content).startswith(LOOP_PREFIX) for m in msgs
        )
        reason = None
        if loops >= self.max_loop_hits:
            reason = "loop_detected"
        elif steps >= self.max_steps:
            reason = "max_steps"
        elif cost >= self.max_tool_cost:
            reason = "max_tool_cost"
        if reason:
            text = f"{STOP_PREFIX} {reason} (steps={steps}, cost={cost}, loop_hits={loops})"
            return {"jump_to": "end", "messages": [AIMessage(text)]}
        return None

    def wrap_tool_call(self, request: Any, handler: Any) -> Any:
        call = request.tool_call
        key = (call["name"], json.dumps(call["args"], sort_keys=True))
        msgs = request.state["messages"]
        requested = sum(
            (tc["name"], json.dumps(tc["args"], sort_keys=True)) == key
            for m in msgs
            if isinstance(m, AIMessage)
            for tc in m.tool_calls
        )
        if requested >= 2:
            return ToolMessage(
                f"{LOOP_PREFIX}: {call['name']}({call['args']}) was already "
                "executed; reuse the earlier result or try something else.",
                tool_call_id=call["id"],
                name=call["name"],
                status="error",
            )
        cost = spent(msgs) + TOOL_COST.get(call["name"], 0)
        if cost > self.max_tool_cost:
            return ToolMessage(
                f"{BUDGET_PREFIX}: {call['name']} would bring cost to {cost} > "
                f"{self.max_tool_cost}; not executed.",
                tool_call_id=call["id"],
                name=call["name"],
                status="error",
            )
        return handler(request)
