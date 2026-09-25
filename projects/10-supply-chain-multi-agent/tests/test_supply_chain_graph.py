import pytest
from langchain_core.messages import AIMessage
from langgraph.types import Command

from shared.llm import MockChatModel
from supply_chain.agents import build_specialists, mock_supplier
from supply_chain.graph import build_graph, default_llms
from supply_chain.policy import need_qty
from supply_chain.state import FinalReport

APPROVE = Command(resume={"approved": True, "approver": "buyer-1"})
REJECT = Command(resume={"approved": False, "approver": "buyer-1"})


def names(hops):
    return [h["agent"] for h in hops]


# ---- routing ---------------------------------------------------------------------------
def test_routing_order_for_reorder_sku(graph, start):
    result, cfg = start(graph, "SKU-100")
    order = names(result["hops"])
    assert order[0] == "supervisor"
    assert set(order[1:3]) == {"demand_agent", "inventory_agent"}
    assert order[3:] == ["supervisor", "supplier_agent", "supervisor", "reviewer"]
    decisions = [h["decision"] for h in result["hops"] if h["agent"] == "supervisor"]
    assert decisions == [["demand", "inventory"], ["supplier"], ["FINISH"]]
    assert graph.get_state(cfg).next == ("human_approval",)


def test_parallel_fan_out_then_single_join(graph, start):
    result, _ = start(graph, "SKU-100")
    hops = result["hops"]
    demand = next(h for h in hops if h["agent"] == "demand_agent")
    inventory = next(h for h in hops if h["agent"] == "inventory_agent")
    assert demand["step"] == inventory["step"]  # same super-step = concurrent
    supervisors_next = [
        h for h in hops if h["agent"] == "supervisor" and h["step"] == demand["step"] + 1
    ]
    assert len(supervisors_next) == 1  # join: supervisor runs once after both
    slots = result["slots"]
    assert slots["forecast"]["total_units"] == 549  # merged by the dict reducer
    assert slots["stock"]["on_hand"] == 200 and slots["stock"]["open_po_qty"] == 100
    assert need_qty(slots) == 549 - 200 - 100 + 60


def test_no_reorder_path_skips_supplier(graph, start, services):
    result, _ = start(graph, "SKU-200")
    assert "__interrupt__" not in result
    assert "supplier_agent" not in names(result["hops"])
    assert result["final"]["outcome"] == "no_reorder"
    assert services.erp.drafts == {} and services.erp.submitted == []


# ---- supplier / reviewer ---------------------------------------------------------------
def test_fallback_supplier_when_preferred_quote_unavailable(graph, start, services):
    result, cfg = start(graph, "SKU-300")
    rec = result["slots"]["recommendation"]
    assert rec["supplier"] == "Stark"  # Umbrella down; Wayne's 30d lead time unacceptable
    hop = next(h for h in result["hops"] if h["agent"] == "supplier_agent")
    assert hop["unavailable"] == ["Umbrella"]
    result = graph.invoke(APPROVE, cfg)
    assert services.erp.submitted[0]["supplier"] == "Stark"


def test_reviewer_loops_back_once_and_fixes_supplier(graph, start, services):
    result, cfg = start(graph, "SKU-400")
    reviews = [h for h in result["hops"] if h["agent"] == "reviewer"]
    assert [r["passed"] for r in reviews] == [False, True]
    assert "PiedPiper" in reviews[0]["issues"][0]
    assert names(result["hops"]).count("supplier_agent") == 2
    assert result["revisions"] == 1
    assert result["slots"]["recommendation"]["supplier"] == "PiedPiper"
    result = graph.invoke(APPROVE, cfg)
    assert len(services.erp.drafts) == 2 and len(services.erp.submitted) == 1
    assert services.erp.submitted[0]["draft_id"] == "DRAFT-002"


def test_reviewer_gives_up_after_one_revision(services, start):
    def stubborn(msgs):  # ignores reviewer feedback: always drafts with preferred Hooli
        out = mock_supplier(msgs)
        if out.tool_calls and out.tool_calls[0]["name"] == "draft_purchase_order":
            call = out.tool_calls[0]
            args = {**call["args"], "supplier": "Hooli", "unit_price": 5.0}
            return AIMessage("", tool_calls=[{**call, "args": args}])
        return out

    graph = build_graph(services, llms={"supplier": MockChatModel(responder=stubborn)})
    result, _ = start(graph, "SKU-400")
    assert "__interrupt__" not in result
    assert result["final"]["outcome"] == "review_failed"
    assert result["final"]["review_issues"]
    assert services.erp.submitted == []


def test_recommendation_cites_producing_agent_for_every_number(graph, start):
    result, _ = start(graph, "SKU-100")
    cites = result["slots"]["recommendation"]["citations"]
    assert cites["forecast_units"].startswith("demand_agent.")
    assert all(
        cites[k].startswith("inventory_agent.") for k in ("on_hand", "open_po_qty", "safety_stock")
    )
    assert cites["unit_price"] == "supplier_agent.get_quote(Acme)"


# ---- human in the loop + idempotency -----------------------------------------------------
def test_hitl_approve_submits_po(graph, start, services):
    result, cfg = start(graph, "SKU-100")
    payload = result["__interrupt__"][0].value
    assert payload["recommendation"]["qty"] == 309
    assert services.erp.submitted == []  # nothing sent while paused
    result = graph.invoke(APPROVE, cfg)
    final = FinalReport.model_validate(result["final"])
    assert final.outcome == "po_submitted" and final.po_number
    assert len(services.erp.submitted) == 1
    assert services.notifier.sent


def test_hitl_reject_never_submits(graph, start, services):
    _, cfg = start(graph, "SKU-100")
    result = graph.invoke(REJECT, cfg)
    assert result["final"]["outcome"] == "po_rejected"
    assert services.erp.submitted == [] and services.erp.submit_calls == 0


def test_idempotent_submit_after_crash(graph, start, services):
    _, cfg = start(graph, "SKU-100")
    services.notifier.fail_next = 1  # PO is sent, then the notification call fails
    with pytest.raises(ConnectionError):
        graph.invoke(APPROVE, cfg)
    assert len(services.erp.submitted) == 1
    assert graph.get_state(cfg).next == ("submit_po",)
    result = graph.invoke(None, cfg)  # retry from checkpoint re-runs submit_po
    assert result["submission"]["replayed"] is True
    assert services.erp.submit_calls == 2 and len(services.erp.submitted) == 1


# ---- guards ------------------------------------------------------------------------------
def test_max_iteration_guard_stops_looping_supervisor(services, start):
    loopy = MockChatModel(
        responder=lambda _: '{"next_agent": "demand", "parallel": [], "reason": "again"}'
    )
    graph = build_graph(services, llms={"supervisor": loopy}, max_iterations=4)
    result, _ = start(graph, "SKU-100")
    assert result["final"]["outcome"] == "halted_budget"
    assert names(result["hops"]).count("demand_agent") == 4
    assert names(result["hops"]).count("supervisor") == 5  # 4 routed + 1 halt
    assert services.erp.drafts == {}


def test_cost_budget_guard(services, start):
    graph = build_graph(services, max_cost_units=5)
    result, _ = start(graph, "SKU-100")
    assert result["final"]["outcome"] == "halted_budget"
    assert "supplier_agent" not in names(result["hops"])


@pytest.mark.parametrize(
    "bad_output",
    ['{"next_agent": "supplier", "parallel": [], "reason": "skip ahead"}', "I think demand?"],
)
def test_supervisor_guard_overrides_invalid_or_unparseable(services, start, bad_output):
    graph = build_graph(
        services, llms={"supervisor": MockChatModel(responder=lambda _: bad_output)}
    )
    result, _ = start(graph, "SKU-200")
    first = result["hops"][0]
    assert first["overridden"] is True and first["reason"].startswith("guard")
    assert first["decision"] == ["demand", "inventory"]


def test_guard_fallback_when_specialist_skips_tools(services, start):
    lazy = MockChatModel(responder=lambda _: AIMessage("Demand looks fine to me."))
    graph = build_graph(services, llms={"demand": lazy})
    result, _ = start(graph, "SKU-100")
    assert result["slots"]["forecast"]["source"] == "demand_agent.guard_fallback"
    assert result["slots"]["forecast"]["total_units"] == 549


def test_least_privilege_tool_scopes(services):
    specs = build_specialists(services, default_llms())
    scopes = {n: {t.name for t in s.tools} for n, s in specs.items()}
    assert scopes == {
        "demand": {"get_sales_history", "forecast_demand"},
        "inventory": {"get_stock_levels", "get_open_pos", "compute_reorder_point"},
        "supplier": {"list_suppliers", "get_quote", "draft_purchase_order"},
    }
    assert not any("submit" in t for tools in scopes.values() for t in tools)
