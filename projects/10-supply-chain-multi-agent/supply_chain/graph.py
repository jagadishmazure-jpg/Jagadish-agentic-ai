"""Supervisor multi-agent graph.

START -> supervisor --(Send, parallel)--> demand_agent | inventory_agent  -> supervisor
         supervisor --> supplier_agent -> supervisor
         supervisor --FINISH--> reviewer --pass--> human_approval (interrupt) --> submit_po
                                         --fail (once)--> supplier_agent
         no reorder / sourcing failed / budget exhausted / rejected --> finalize -> END
"""

from __future__ import annotations

import time
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt

from shared.observability import install
from shared.resilience import ModelUnavailableError, exit_record, with_fallback
from shared.tools import SystemOfRecordUnavailableError
from supply_chain import supervisor as sup
from supply_chain.agents import MOCK_RESPONDERS, build_specialists
from supply_chain.policy import (
    DEFAULT_HORIZON_WEEKS,
    MAX_COST_UNITS,
    MAX_ITERATIONS,
    MAX_LEAD_TIME_DAYS,
    MAX_REVISIONS,
    best_quote,
    need_qty,
)
from supply_chain.reviewer import review
from supply_chain.services import POAlreadyReleasedError, Services, seed_services
from supply_chain.sor import build_gateways
from supply_chain.state import FinalReport, Recommendation, RouteDecision, SupplyChainState
from supply_chain.tools import (
    create_draft,
    fetch_history,
    fetch_open_pos,
    fetch_stock,
    forecast_from_history,
    get_quote_payload,
)

AGENT_NODES = {
    "demand": "demand_agent",
    "inventory": "inventory_agent",
    "supplier": "supplier_agent",
}


def default_llms() -> dict[str, BaseChatModel]:
    from shared.llm import get_llm

    return {
        "supervisor": get_llm(mock_responder=sup.mock_supervisor),
        **{name: get_llm(mock_responder=r) for name, r in MOCK_RESPONDERS.items()},
    }


def _step(config: RunnableConfig) -> int:
    return int(config.get("metadata", {}).get("langgraph_step", -1))


def build_graph(
    services: Services | None = None,
    llms: dict[str, BaseChatModel] | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    *,
    max_iterations: int = MAX_ITERATIONS,
    max_cost_units: int = MAX_COST_UNITS,
):
    install()
    services = services or seed_services()
    llms = {k: with_fallback(v) for k, v in {**default_llms(), **(llms or {})}.items()}
    gateways = build_gateways(services)
    specialists = build_specialists(services, llms, gateways)

    def hop(config, agent, started, **extra) -> dict[str, Any]:
        return {
            "step": _step(config),
            "agent": agent,
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            **extra,
        }

    # ---- supervisor -------------------------------------------------------------------
    def supervisor(state: SupplyChainState, config: RunnableConfig) -> dict[str, Any]:
        t0 = time.perf_counter()
        it = state.get("iterations", 0) + 1
        spent = state.get("cost_units", 0)
        if it > max_iterations or spent >= max_cost_units:
            d = RouteDecision(
                next_agent="FINISH",
                reason=f"budget exhausted (iterations={it - 1}/{max_iterations}, "
                f"cost={spent}/{max_cost_units})",
            )
            return {
                "iterations": it,
                "route": d.model_dump(),
                "outcome": "halted_budget",
                "hops": [hop(config, "supervisor", t0, decision="FINISH", reason=d.reason)],
            }
        down = state.get("slots", {}).get("sor_unavailable")
        if down:
            reason = f"{down} unavailable: plan deferred to the next planning run"
            return {
                "iterations": it,
                "route": RouteDecision(next_agent="FINISH", reason=reason).model_dump(),
                "outcome": "sor_unavailable",
                "hops": [hop(config, "supervisor", t0, decision="FINISH", reason=reason)],
            }
        exits: list[dict[str, str]] = []
        try:
            d, overridden = sup.decide(llms["supervisor"], state)
        except ModelUnavailableError:
            fb = sup.plan_next(sup.status(state))
            d = fb.model_copy(update={"reason": f"guard: model unavailable; {fb.reason}"})
            overridden = True
            exits.append(exit_record("supervisor", "degrade", "model down: deterministic routing"))
        targets = [d.next_agent, *d.parallel]
        return {
            "exits": exits,
            "iterations": it,
            "cost_units": 1,
            "route": d.model_dump(),
            "messages": [AIMessage(f"route -> {targets}: {d.reason}", name="supervisor")],
            "hops": [
                hop(
                    config,
                    "supervisor",
                    t0,
                    decision=targets,
                    reason=d.reason,
                    overridden=overridden,
                )
            ],
        }

    def route_from_supervisor(state: SupplyChainState):
        d = state["route"]
        if d["next_agent"] == "FINISH":
            if state.get("outcome") != "halted_budget" and state["slots"].get("recommendation"):
                return "reviewer"
            return "finalize"
        # Send = dynamic fan-out; parallel specialists run in the same super-step and the
        # supervisor runs once after all of them finish (the join).
        return [Send(AGENT_NODES[a], state) for a in [d["next_agent"], *d["parallel"]]]

    # ---- specialists ------------------------------------------------------------------
    def agent_update(config, name, run, slots, t0, **extra) -> dict[str, Any]:
        return {
            "slots": slots,
            "cost_units": run.llm_calls + len(run.tools_called),
            "messages": [AIMessage(run.summary, name=f"{name}_agent")],
            "hops": [
                hop(
                    config,
                    f"{name}_agent",
                    t0,
                    tools=run.tools_called,
                    llm_calls=run.llm_calls,
                    **extra,
                )
            ],
        }

    def demand_agent(state: SupplyChainState, config: RunnableConfig) -> dict[str, Any]:
        t0 = time.perf_counter()
        weeks = state.get("horizon_weeks", DEFAULT_HORIZON_WEEKS)
        run = specialists["demand"].run(
            {"task": "forecast demand", "sku": state["sku"], "weeks": weeks}
        )
        found = [f for f in run.artifacts.get("forecast_demand", []) if "total_units" in f]
        exits = []
        if run.model_unavailable:
            exits.append(exit_record("demand_agent", "degrade", "model down: SMA forecast"))
        if found:
            forecast = {**found[-1], "source": "demand_agent.forecast_demand"}
        else:  # guard: the LLM skipped its tool -> compute deterministically, flag provenance
            try:
                h = fetch_history(gateways["demand"], state["sku"])
            except SystemOfRecordUnavailableError:
                exits.append(exit_record("demand_agent", "retry", "analytics down: next run"))
                slots = {"forecast": None, "sor_unavailable": "analytics"}
                return agent_update(config, "demand", run, slots, t0) | {"exits": exits}
            forecast = {
                **forecast_from_history(h, weeks),
                "weeks": weeks,
                "source": "demand_agent.guard_fallback",
            }
        return agent_update(config, "demand", run, {"forecast": forecast}, t0) | {"exits": exits}

    def inventory_agent(state: SupplyChainState, config: RunnableConfig) -> dict[str, Any]:
        t0 = time.perf_counter()
        sku = state["sku"]
        run = specialists["inventory"].run({"task": "stock position", "sku": sku})
        a = {k: v[-1] for k, v in run.artifacts.items() if "unavailable" not in v[-1]}
        guard = "inventory_agent.guard_fallback"
        exits = []
        if run.model_unavailable:
            exits.append(exit_record("inventory_agent", "degrade", "model down: direct ERP read"))
        erp_stock: dict[str, Any] = {}
        fb_open_qty = 0
        if not {"get_stock_levels", "get_open_pos", "compute_reorder_point"} <= a.keys():
            try:  # guard fallback reads the ERP directly through the same scoped gateway
                erp_stock = fetch_stock(gateways["inventory"], sku)
                fb_open_qty = sum(p["qty"] for p in fetch_open_pos(gateways["inventory"], sku))
            except SystemOfRecordUnavailableError:
                exits.append(exit_record("inventory_agent", "retry", "ERP down: next run"))
                slots = {"stock": None, "sor_unavailable": "erp"}
                return agent_update(config, "inventory", run, slots, t0) | {"exits": exits}

        def pick(tool: str, key: str, fallback: Any) -> tuple[Any, str]:
            if tool in a:
                return a[tool][key], f"inventory_agent.{tool}"
            return fallback, guard

        on_hand, s1 = pick("get_stock_levels", "on_hand", erp_stock.get("on_hand", 0))
        open_qty, s2 = pick("get_open_pos", "open_po_qty", fb_open_qty)
        safety, s3 = pick("compute_reorder_point", "safety_stock", erp_stock.get("safety_stock", 0))
        rop, _ = pick("compute_reorder_point", "reorder_point", erp_stock.get("reorder_point", 0))
        stock = {
            "on_hand": on_hand,
            "open_po_qty": open_qty,
            "safety_stock": safety,
            "reorder_point": rop,
            "sources": {"on_hand": s1, "open_po_qty": s2, "safety_stock": s3},
        }
        return agent_update(config, "inventory", run, {"stock": stock}, t0) | {"exits": exits}

    def supplier_agent(state: SupplyChainState, config: RunnableConfig) -> dict[str, Any]:
        t0 = time.perf_counter()
        slots = state["slots"]
        need = need_qty(slots) or 0
        feedback = slots.get("reviewer_feedback") or {}
        task = {
            "task": "source and draft a purchase order",
            "sku": state["sku"],
            "need_qty": need,
            "max_lead_time_days": MAX_LEAD_TIME_DAYS,
            "reviewer_feedback": feedback.get("issues", []),
            "required_supplier": feedback.get("expected_supplier"),
        }
        run = specialists["supplier"].run(task)
        exits = []
        if run.model_unavailable:
            run = deterministic_sourcing(run, task)
            exits.append(
                exit_record("supplier_agent", "degrade", "model down: cheapest acceptable")
            )
        quotes = run.artifacts.get("get_quote", [])
        drafts = [d for d in run.artifacts.get("draft_purchase_order", []) if "draft_id" in d]
        if any(q.get("injection_neutralised") for q in quotes):
            exits.append(exit_record("supplier_agent", "degrade", "supplier text neutralised"))
        new_slots: dict[str, Any] = {"quotes": quotes}
        if not drafts:
            new_slots |= {"sourcing_failed": True, "recommendation": None}
            exits.append(exit_record("supplier_agent", "escalate", "no draft: buyer notified"))
        else:
            d = drafts[-1]
            q = next((x for x in quotes if x["supplier"] == d["supplier"]), {})
            stock_src = slots["stock"]["sources"]
            rec = Recommendation(
                sku=d["sku"],
                qty=d["qty"],
                supplier=d["supplier"],
                unit_price=d["unit_price"],
                lead_time_days=q.get("lead_time_days", 999),
                total_cost=d["total"],
                draft_id=d["draft_id"],
                need_qty=need,
                citations={
                    "forecast_units": slots["forecast"]["source"],
                    "on_hand": stock_src["on_hand"],
                    "open_po_qty": stock_src["open_po_qty"],
                    "safety_stock": stock_src["safety_stock"],
                    "unit_price": f"supplier_agent.get_quote({d['supplier']})" if q else "",
                    "qty": "supplier_agent.draft_purchase_order",
                },
            )
            new_slots |= {"recommendation": rec.model_dump(), "sourcing_failed": False}
        unavailable = [q["supplier"] for q in quotes if not q.get("available")]
        return agent_update(config, "supplier", run, new_slots, t0, unavailable=unavailable) | {
            "exits": exits
        }

    def deterministic_sourcing(run: Any, task: dict[str, Any]) -> Any:
        """Degrade path when every model deployment is down: the same tools, same policy
        (cheapest acceptable quote, reviewer's pick if any), no LLM."""
        gw, sku, need = gateways["supplier"], task["sku"], task["need_qty"]
        artifacts: dict[str, list[dict[str, Any]]] = {"get_quote": []}
        called = ["list_suppliers"]
        try:
            sups = gw.call("suppliers", "list_suppliers", sku=sku)
        except SystemOfRecordUnavailableError:
            sups = []
        for s in sups:
            artifacts["get_quote"].append(get_quote_payload(gw, s["supplier"], sku, need))
            called.append("get_quote")
        by_name = {q["supplier"]: q for q in artifacts["get_quote"] if q.get("available")}
        pick = by_name.get(task.get("required_supplier") or "") or best_quote(
            artifacts["get_quote"]
        )
        if pick:
            called.append("draft_purchase_order")
            try:
                d = create_draft(
                    gw, pick["supplier"], sku, max(need, pick["moq"]), pick["unit_price"]
                )
                artifacts["draft_purchase_order"] = [d]
            except SystemOfRecordUnavailableError:
                pass
        run.tools_called, run.artifacts = called, artifacts
        run.summary = f"deterministic sourcing: {pick['supplier'] if pick else 'no supplier'}"
        return run

    # ---- reviewer / critic ------------------------------------------------------------
    def reviewer(state: SupplyChainState, config: RunnableConfig) -> Command:
        t0 = time.perf_counter()
        r = review(state["slots"])
        revisions = state.get("revisions", 0)
        entry = hop(config, "reviewer", t0, passed=r["passed"], issues=r["issues"])
        update: dict[str, Any] = {"review": r, "hops": [entry]}
        if r["passed"]:
            msg = f"review passed for {r['draft_id']}"
            return Command(
                goto="human_approval",
                update=update | {"messages": [AIMessage(msg, name="reviewer")]},
            )
        if revisions < MAX_REVISIONS:
            update |= {
                "revisions": revisions + 1,
                "slots": {"recommendation": None, "reviewer_feedback": r},
                "messages": [AIMessage(f"revise: {r['issues']}", name="reviewer")],
            }
            return Command(goto="supplier_agent", update=update)
        return Command(goto="finalize", update=update | {"outcome": "review_failed"})

    # ---- human in the loop + side effects ---------------------------------------------
    def human_approval(state: SupplyChainState, config: RunnableConfig) -> Command:
        rec = state["slots"]["recommendation"]
        # Pauses here; checkpointer persists state. Resume with Command(resume={...}).
        decision = interrupt(
            {"type": "po_approval", "recommendation": rec, "review": state["review"]}
        )
        if isinstance(decision, bool):
            decision = {"approved": decision}
        approval = {
            "approved": bool(decision.get("approved")),
            "approver": decision.get("approver", "unknown"),
            "note": decision.get("note", ""),
        }
        entry = {"step": _step(config), "agent": "human_approval", **approval}
        update = {"approval": approval, "hops": [entry]}
        if approval["approved"]:
            return Command(goto="submit_po", update=update)
        return Command(goto="finalize", update=update | {"outcome": "po_rejected"})

    def submit_po(state: SupplyChainState, config: RunnableConfig) -> dict[str, Any]:
        t0 = time.perf_counter()
        draft_id = state["slots"]["recommendation"]["draft_id"]
        gw = gateways["orchestrator"]
        try:
            po = gw.call(
                "erp",
                "submit_purchase_order",
                draft_id=draft_id,
                idempotency_key=f"po-submit:{draft_id}",
                dry_run=False,
            )
        except SystemOfRecordUnavailableError as exc:
            return compensate_submit(state, config, t0, draft_id, exc)
        services.notifier.send(f"PO {po['po_number']} submitted to {po['supplier']}")
        return {
            "submission": po,
            "outcome": "po_submitted",
            "hops": [
                hop(config, "submit_po", t0, po_number=po["po_number"], replayed=po["replayed"])
            ],
        }

    def compensate_submit(state, config, t0, draft_id: str, exc: Exception) -> dict[str, Any]:
        """ERP release failed after retries: cancel the draft (undo the partial side effect)
        so no stale draft can be released later; the buyer re-plans on the next run."""
        gw = gateways["orchestrator"]
        try:
            gw.call(
                "erp",
                "cancel_po_draft",
                draft_id=draft_id,
                reason=f"release failed: {exc}",
                idempotency_key=f"po-cancel:{draft_id}",
                dry_run=False,
            )
            ex = exit_record("submit_po", "compensate", f"release failed: {draft_id} cancelled")
        except POAlreadyReleasedError:
            ex = exit_record("submit_po", "escalate", "ERP says released: buyer reconciles")
        except SystemOfRecordUnavailableError:
            ex = exit_record("submit_po", "escalate", "ERP down: buyer cancels draft manually")
        services.notifier.send(f"PO release for {draft_id} failed ({ex['exit']}): {ex['reason']}")
        return {
            "outcome": "submit_failed",
            "exits": [ex],
            "hops": [hop(config, "submit_po", t0, error=str(exc), exit=ex["exit"])],
        }

    def finalize(state: SupplyChainState, config: RunnableConfig) -> dict[str, Any]:
        slots = state.get("slots", {})
        outcome = state.get("outcome")
        if outcome is None:
            outcome = "no_reorder" if need_qty(slots) == 0 else "no_supplier"
        rec = slots.get("recommendation")
        po = state.get("submission") or {}
        summaries = {
            "po_submitted": f"PO {po.get('po_number')} submitted: "
            f"{rec and rec['qty']} x {state['sku']} from {rec and rec['supplier']}.",
            "no_reorder": f"No reorder for {state['sku']}: stock covers forecast + safety stock.",
            "po_rejected": f"Recommendation for {state['sku']} rejected by approver.",
            "review_failed": f"Recommendation for {state['sku']} failed review twice; "
            "escalated to a buyer.",
            "no_supplier": f"No acceptable supplier quote for {state['sku']}; buyer notified.",
            "halted_budget": f"Stopped planning {state['sku']}: iteration/cost budget exhausted.",
            "sor_unavailable": f"Planning for {state['sku']} deferred: a system of record was "
            "unavailable after retries; nothing drafted.",
            "submit_failed": f"PO release for {state['sku']} failed; draft compensated and the "
            "buyer notified. Re-plan on the next run.",
        }
        report = FinalReport(
            sku=state["sku"],
            outcome=outcome,
            summary=summaries[outcome],
            recommendation=rec,
            po_number=po.get("po_number"),
            review_issues=(state.get("review") or {}).get("issues", []),
            agent_hops=sum(1 for h in state.get("hops", []) if h["agent"].endswith("_agent")),
        )
        return {"outcome": outcome, "final": report.model_dump()}

    # ---- wiring -----------------------------------------------------------------------
    g = StateGraph(SupplyChainState)
    g.add_node("supervisor", supervisor)
    g.add_node("demand_agent", demand_agent)
    g.add_node("inventory_agent", inventory_agent)
    g.add_node("supplier_agent", supplier_agent)
    g.add_node("reviewer", reviewer, destinations=("human_approval", "supplier_agent", "finalize"))
    g.add_node("human_approval", human_approval, destinations=("submit_po", "finalize"))
    g.add_node("submit_po", submit_po)
    g.add_node("finalize", finalize)

    g.add_edge(START, "supervisor")
    g.add_conditional_edges(
        "supervisor",
        route_from_supervisor,
        [*AGENT_NODES.values(), "reviewer", "finalize"],
    )
    for node in AGENT_NODES.values():
        g.add_edge(node, "supervisor")
    g.add_edge("submit_po", "finalize")
    g.add_edge("finalize", END)
    return g.compile(checkpointer=checkpointer or MemorySaver(), name="supply_chain")
