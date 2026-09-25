"""Per-agent tool sets. Each factory closes over ONE scoped gateway (least privilege).

Tools return ``(summary_for_llm, artifact)``: the LLM reads the summary, while the graph
reads the typed artifact so numbers never pass through LLM text.
Every tool now crosses an MCP boundary through its agent's scoped ``ToolGateway``. When a
system of record is down the tool returns an ``{"unavailable": ...}`` artifact instead of
raising, so the graph (not the LLM) decides the exit.
Note: there is deliberately no ``submit_purchase_order`` tool; submission is a graph node
behind human approval.
"""

from __future__ import annotations

import math
from typing import Any

from langchain_core.tools import BaseTool, tool

from shared.tools import SystemOfRecordUnavailableError, ToolGateway

MARKER = "[removed: suspected injected instruction]"


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


def _thread() -> str:
    """Planning-run id for idempotency keys (the LangGraph thread when inside a run)."""
    try:
        from langgraph.config import get_config

        return str(get_config().get("configurable", {}).get("thread_id", "adhoc"))
    except RuntimeError:
        return "adhoc"


def _down(system: str, exc: Exception) -> tuple[str, dict]:
    return f"{system} unavailable: {exc}", {"unavailable": system, "error": str(exc)}


def fetch_history(gw: ToolGateway, sku: str) -> list[int]:
    """Weekly units from the certified semantic model (raises if analytics is down)."""
    return list(gw.call("analytics", "get_measure", measure="weekly_units", entity=sku)["values"])


def fetch_stock(gw: ToolGateway, sku: str) -> dict[str, Any]:
    return gw.call("erp", "get_stock", sku=sku)


def fetch_open_pos(gw: ToolGateway, sku: str) -> list[dict[str, Any]]:
    return gw.call("erp", "get_open_purchase_orders", sku=sku)


def demand_tools(gw: ToolGateway) -> list[BaseTool]:
    @tool(response_format="content_and_artifact")
    def get_sales_history(sku: str) -> tuple[str, dict]:
        """Weekly unit sales for a SKU, oldest first (last 8 weeks)."""
        try:
            h = fetch_history(gw, sku)
        except SystemOfRecordUnavailableError as exc:
            return _down("analytics", exc)
        return f"{sku} weekly sales: {h}", {"sku": sku, "weekly_sales": h}

    @tool(response_format="content_and_artifact")
    def forecast_demand(sku: str, weeks: int) -> tuple[str, dict]:
        """Forecast total unit demand for a SKU over the next `weeks` weeks."""
        try:
            h = fetch_history(gw, sku)
        except SystemOfRecordUnavailableError as exc:
            return _down("analytics", exc)
        f = {"sku": sku, "weeks": weeks, **forecast_from_history(h, weeks)}
        return f"{sku} forecast {f['total_units']} units / {weeks} wks ({f['method']})", f

    return [get_sales_history, forecast_demand]


def inventory_tools(gw: ToolGateway) -> list[BaseTool]:
    @tool(response_format="content_and_artifact")
    def get_stock_levels(sku: str) -> tuple[str, dict]:
        """Current on-hand stock for a SKU from the ERP."""
        try:
            s = fetch_stock(gw, sku)
        except SystemOfRecordUnavailableError as exc:
            return _down("erp", exc)
        return f"{sku} on hand: {s['on_hand']}", {"sku": sku, "on_hand": s["on_hand"]}

    @tool(response_format="content_and_artifact")
    def get_open_pos(sku: str) -> tuple[str, dict]:
        """Open (not yet received) purchase orders for a SKU."""
        try:
            pos = fetch_open_pos(gw, sku)
        except SystemOfRecordUnavailableError as exc:
            return _down("erp", exc)
        qty = sum(p["qty"] for p in pos)
        return f"{sku} open POs: {len(pos)} totalling {qty}", {"open_pos": pos, "open_po_qty": qty}

    @tool(response_format="content_and_artifact")
    def compute_reorder_point(sku: str) -> tuple[str, dict]:
        """MRP parameters for a SKU: reorder point, safety stock and replenishment lead time."""
        try:
            s = fetch_stock(gw, sku)
        except SystemOfRecordUnavailableError as exc:
            return _down("erp", exc)
        a = {k: s[k] for k in ("reorder_point", "safety_stock", "lead_time_days")}
        return f"{sku} ROP {a['reorder_point']}, safety stock {a['safety_stock']}", a

    return [get_stock_levels, get_open_pos, compute_reorder_point]


def get_quote_payload(gw: ToolGateway, supplier: str, sku: str, qty: int) -> dict[str, Any]:
    try:
        q = gw.call("suppliers", "get_supplier_quote", supplier=supplier, sku=sku, qty=qty)
    except SystemOfRecordUnavailableError as exc:
        return {"supplier": supplier, "available": False, "error": f"portal unavailable: {exc}"}
    if MARKER in str(q):
        q = {**q, "injection_neutralised": True}
    return q


def create_draft(
    gw: ToolGateway, supplier: str, sku: str, qty: int, unit_price: float
) -> dict[str, Any]:
    po = {
        "supplier": supplier,
        "sku": sku,
        "qty": qty,
        "unit_price": unit_price,
        "total": round(qty * unit_price, 2),
    }
    key = f"draft:{_thread()}:{sku}:{supplier}:{qty}:{unit_price}"
    return gw.call("erp", "create_po_draft", po=po, idempotency_key=key, dry_run=False)


def supplier_tools(gw: ToolGateway) -> list[BaseTool]:
    @tool(response_format="content_and_artifact")
    def list_suppliers(sku: str) -> tuple[str, dict]:
        """Approved suppliers for a SKU (with preferred flag)."""
        try:
            s = gw.call("suppliers", "list_suppliers", sku=sku)
        except SystemOfRecordUnavailableError as exc:
            return f"supplier portal unavailable: {exc}", {
                "suppliers": [],
                "unavailable": "suppliers",
            }
        return f"{sku} suppliers: {s}", {"suppliers": s}

    @tool(response_format="content_and_artifact")
    def get_quote(supplier: str, sku: str, qty: int) -> tuple[str, dict]:
        """Request a price / lead-time quote from one supplier."""
        q = get_quote_payload(gw, supplier, sku, qty)
        return f"quote {supplier}: {q}", q

    @tool(response_format="content_and_artifact")
    def draft_purchase_order(
        supplier: str, sku: str, qty: int, unit_price: float
    ) -> tuple[str, dict]:
        """Create a DRAFT purchase order (never sent to the supplier by this tool)."""
        try:
            d = create_draft(gw, supplier, sku, qty, unit_price)
        except SystemOfRecordUnavailableError as exc:
            return _down("erp", exc)
        return f"draft {d['draft_id']} created: {qty} x {sku} @ {unit_price} from {supplier}", d

    return [list_suppliers, get_quote, draft_purchase_order]
