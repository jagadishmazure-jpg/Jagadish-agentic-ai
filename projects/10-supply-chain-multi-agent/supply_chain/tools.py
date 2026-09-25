"""Per-agent tool sets. Each factory closes over ONE backing system (least privilege).

Tools return ``(summary_for_llm, artifact)``: the LLM reads the summary, while the graph
reads the typed artifact so numbers never pass through LLM text.
Note: there is deliberately no ``submit_purchase_order`` tool; submission is a graph node
behind human approval.
"""

from __future__ import annotations

import math
from typing import Any

from langchain_core.tools import BaseTool, tool

from supply_chain.services import Erp, SalesWarehouse, SupplierNetwork


def forecast_from_history(history: list[int], weeks: int) -> dict[str, Any]:
    """4-week simple moving average plus linear trend vs the prior 4 weeks."""
    if not history:
        return {"weekly": [0] * weeks, "total_units": 0, "method": "no history"}
    last = history[-4:]
    prev = history[-8:-4] or last
    avg = sum(last) / len(last)
    trend = (avg - sum(prev) / len(prev)) / len(last)
    weekly = [round(max(0.0, avg + trend * i), 2) for i in range(1, weeks + 1)]
    return {
        "weekly": weekly,
        "total_units": math.ceil(sum(weekly)),
        "method": f"SMA(4)={avg:.2f} + trend {trend:+.3f}/wk",
    }


def demand_tools(sales: SalesWarehouse) -> list[BaseTool]:
    @tool(response_format="content_and_artifact")
    def get_sales_history(sku: str) -> tuple[str, dict]:
        """Weekly unit sales for a SKU, oldest first (last 8 weeks)."""
        h = sales.history(sku)
        return f"{sku} weekly sales: {h}", {"sku": sku, "weekly_sales": h}

    @tool(response_format="content_and_artifact")
    def forecast_demand(sku: str, weeks: int) -> tuple[str, dict]:
        """Forecast total unit demand for a SKU over the next `weeks` weeks."""
        f = {"sku": sku, "weeks": weeks, **forecast_from_history(sales.history(sku), weeks)}
        return f"{sku} forecast {f['total_units']} units / {weeks} wks ({f['method']})", f

    return [get_sales_history, forecast_demand]


def inventory_tools(erp: Erp) -> list[BaseTool]:
    @tool(response_format="content_and_artifact")
    def get_stock_levels(sku: str) -> tuple[str, dict]:
        """Current on-hand stock for a SKU from the ERP."""
        s = erp.stock(sku) or {"on_hand": 0}
        return f"{sku} on hand: {s['on_hand']}", {"sku": sku, "on_hand": s["on_hand"]}

    @tool(response_format="content_and_artifact")
    def get_open_pos(sku: str) -> tuple[str, dict]:
        """Open (not yet received) purchase orders for a SKU."""
        pos = erp.open_pos(sku)
        qty = sum(p["qty"] for p in pos)
        return f"{sku} open POs: {len(pos)} totalling {qty}", {"open_pos": pos, "open_po_qty": qty}

    @tool(response_format="content_and_artifact")
    def compute_reorder_point(sku: str) -> tuple[str, dict]:
        """MRP parameters for a SKU: reorder point, safety stock and replenishment lead time."""
        s = erp.stock(sku) or {"reorder_point": 0, "safety_stock": 0, "lead_time_days": 0}
        a = {k: s[k] for k in ("reorder_point", "safety_stock", "lead_time_days")}
        return f"{sku} ROP {a['reorder_point']}, safety stock {a['safety_stock']}", a

    return [get_stock_levels, get_open_pos, compute_reorder_point]


def supplier_tools(network: SupplierNetwork, erp: Erp) -> list[BaseTool]:
    @tool(response_format="content_and_artifact")
    def list_suppliers(sku: str) -> tuple[str, dict]:
        """Approved suppliers for a SKU (with preferred flag)."""
        s = network.suppliers(sku)
        return f"{sku} suppliers: {s}", {"suppliers": s}

    @tool(response_format="content_and_artifact")
    def get_quote(supplier: str, sku: str, qty: int) -> tuple[str, dict]:
        """Request a price / lead-time quote from one supplier."""
        q = network.quote(supplier, sku, qty)
        return f"quote {supplier}: {q}", q

    @tool(response_format="content_and_artifact")
    def draft_purchase_order(
        supplier: str, sku: str, qty: int, unit_price: float
    ) -> tuple[str, dict]:
        """Create a DRAFT purchase order (never sent to the supplier by this tool)."""
        d = erp.create_draft(
            supplier=supplier,
            sku=sku,
            qty=qty,
            unit_price=unit_price,
            total=round(qty * unit_price, 2),
        )
        return f"draft {d['draft_id']} created: {qty} x {sku} @ {unit_price} from {supplier}", d

    return [list_suppliers, get_quote, draft_purchase_order]
