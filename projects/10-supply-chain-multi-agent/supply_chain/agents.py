"""Specialist agents: each is a LangChain tool-calling agent (``create_agent``) with its
own prompt and tool set. ``Specialist.run`` is the only interface the supervisor graph
uses, so any specialist can be swapped for a remote agent (e.g. an A2A client to a
Databricks or SAP agent) without touching the graph.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.tools import BaseTool

from supply_chain.policy import MAX_LEAD_TIME_DAYS, best_quote
from supply_chain.services import Services
from supply_chain.tools import demand_tools, inventory_tools, supplier_tools

PROMPTS = {
    "demand": (
        "You are the demand-planning agent. Use your tools to fetch sales history and forecast "
        "demand for the SKU over the requested horizon. Reply with a one-line summary."
    ),
    "inventory": (
        "You are the inventory agent (SAP). Use your tools to get on-hand stock, open purchase "
        "orders and MRP parameters (reorder point, safety stock) for the SKU. One-line summary."
    ),
    "supplier": (
        "You are the sourcing agent. List approved suppliers, get a quote from each for the "
        "needed quantity, then draft ONE purchase order with the cheapest supplier whose lead "
        f"time is <= {MAX_LEAD_TIME_DAYS} days and whose quote is available. Order at least the "
        "needed quantity (respect MOQ). If reviewer_feedback is present, follow it. You can "
        "only DRAFT purchase orders; you cannot send them. Reply with a one-line summary."
    ),
}


@dataclass
class AgentRun:
    summary: str
    tools_called: list[str]
    artifacts: dict[str, list[dict[str, Any]]]
    llm_calls: int
    duration_ms: float


@dataclass
class Specialist:
    name: str
    tools: list[BaseTool]
    runnable: Any  # compiled create_agent graph

    def run(self, task: dict[str, Any]) -> AgentRun:
        start = time.perf_counter()
        out = self.runnable.invoke({"messages": [HumanMessage(json.dumps(task))]})
        msgs: list[BaseMessage] = out["messages"]
        artifacts: dict[str, list[dict[str, Any]]] = {}
        tools_called: list[str] = []
        for m in msgs:
            if isinstance(m, ToolMessage):
                tools_called.append(m.name or "?")
                if isinstance(m.artifact, dict):
                    artifacts.setdefault(m.name or "?", []).append(m.artifact)
        return AgentRun(
            summary=str(msgs[-1].content),
            tools_called=tools_called,
            artifacts=artifacts,
            llm_calls=sum(isinstance(m, AIMessage) for m in msgs),
            duration_ms=round((time.perf_counter() - start) * 1000, 2),
        )


# ---- deterministic mock "LLMs" for each specialist ------------------------------------------
def _task(msgs: Sequence[BaseMessage]) -> dict[str, Any]:
    first_human = next(m for m in msgs if isinstance(m, HumanMessage))
    return json.loads(str(first_human.content))


def _last_tool_batch(msgs: Sequence[BaseMessage]) -> list[ToolMessage]:
    batch: list[ToolMessage] = []
    for m in reversed(msgs):
        if not isinstance(m, ToolMessage):
            break
        batch.insert(0, m)
    return batch


def _calls(*calls: tuple[str, dict[str, Any]]) -> AIMessage:
    return AIMessage(
        "",
        tool_calls=[
            {"name": n, "args": a, "id": f"call_{n}_{i}"} for i, (n, a) in enumerate(calls)
        ],
    )


def mock_demand(msgs: Sequence[BaseMessage]) -> AIMessage:
    t = _task(msgs)
    batch = _last_tool_batch(msgs)
    if not batch:
        return _calls(
            ("get_sales_history", {"sku": t["sku"]}),
            ("forecast_demand", {"sku": t["sku"], "weeks": t["weeks"]}),
        )
    f = next(m.artifact for m in batch if m.name == "forecast_demand")
    return AIMessage(f"Forecast for {t['sku']}: {f['total_units']} units over {f['weeks']} weeks.")


def mock_inventory(msgs: Sequence[BaseMessage]) -> AIMessage:
    sku = _task(msgs)["sku"]
    batch = _last_tool_batch(msgs)
    if not batch:
        return _calls(
            ("get_stock_levels", {"sku": sku}),
            ("get_open_pos", {"sku": sku}),
            ("compute_reorder_point", {"sku": sku}),
        )
    a = {m.name: m.artifact for m in batch}
    return AIMessage(
        f"{sku}: on hand {a['get_stock_levels']['on_hand']}, open POs "
        f"{a['get_open_pos']['open_po_qty']}, safety stock "
        f"{a['compute_reorder_point']['safety_stock']}."
    )


def mock_supplier(msgs: Sequence[BaseMessage]) -> AIMessage:
    """Behaves like a plausible-but-imperfect LLM: favours the *preferred* supplier when its
    quote is available, even if an acceptable cheaper one exists. The reviewer catches that."""
    t = _task(msgs)
    batch = _last_tool_batch(msgs)
    step = batch[0].name if batch else None
    if step is None:
        return _calls(("list_suppliers", {"sku": t["sku"]}))
    if step == "list_suppliers":
        sups = batch[0].artifact["suppliers"]
        return _calls(
            *[
                ("get_quote", {"supplier": s["supplier"], "sku": t["sku"], "qty": t["need_qty"]})
                for s in sups
            ]
        )
    if step == "get_quote":
        quotes = [m.artifact for m in batch]
        preferred = {
            s["supplier"]
            for m in msgs
            if isinstance(m, ToolMessage) and m.name == "list_suppliers"
            for s in m.artifact["suppliers"]
            if s["preferred"]
        }
        by_name = {q["supplier"]: q for q in quotes if q.get("available")}
        pick = (
            by_name.get(t.get("required_supplier") or "")
            or next((by_name[p] for p in preferred if p in by_name), None)
            or best_quote(quotes)
        )
        if pick is None:
            return AIMessage("No supplier quote available; cannot draft a PO.")
        return _calls(
            (
                "draft_purchase_order",
                {
                    "supplier": pick["supplier"],
                    "sku": t["sku"],
                    "qty": max(t["need_qty"], pick["moq"]),
                    "unit_price": pick["unit_price"],
                },
            )
        )
    d = batch[0].artifact
    return AIMessage(f"Drafted {d['draft_id']}: {d['qty']} x {d['sku']} from {d['supplier']}.")


MOCK_RESPONDERS: dict[str, Callable[[Sequence[BaseMessage]], AIMessage]] = {
    "demand": mock_demand,
    "inventory": mock_inventory,
    "supplier": mock_supplier,
}


def build_specialists(services: Services, llms: dict[str, BaseChatModel]) -> dict[str, Specialist]:
    toolsets = {
        "demand": demand_tools(services.sales),
        "inventory": inventory_tools(services.erp),
        "supplier": supplier_tools(services.suppliers, services.erp),
    }
    return {
        name: Specialist(
            name=name,
            tools=tools,
            runnable=create_agent(
                llms[name], tools, system_prompt=PROMPTS[name], name=f"{name}_agent"
            ),
        )
        for name, tools in toolsets.items()
    }
