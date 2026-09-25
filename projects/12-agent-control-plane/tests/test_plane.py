"""Registry + control plane: registration gate, kill switch, promotion gate, tenant policy,
schema rejection and budgets - enforced at the A2A server, not by caller goodwill."""

import pytest
from fastapi.testclient import TestClient

from control_plane.registry import AgentRecord, Budgets, RegistryError
from shared.a2a import A2AClient, A2AError

STOCK = {"sku": "SKU-200"}
FC = {"sku": "SKU-200", "weeks": 4}
DRAFT = {"sku": "SKU-200", "qty": 50, "reason": "restock test", "idempotency_key": "po:test:1"}


def send(net, callee, caller, skill, data, tenant="northwind"):
    return A2AClient(callee, TestClient(net.apps[callee]), caller).send(skill, data, tenant=tenant)


def rejected(net, *args, **kw) -> A2AError:
    with pytest.raises(A2AError) as e:
        send(net, *args, **kw)
    return e.value


def test_agent_card_published_at_well_known(net):
    card = TestClient(net.apps["sap-agent"]).get("/.well-known/agent.json").json()
    assert card["name"] == "sap-agent"
    assert {s["id"] for s in card["skills"]} == {"get_stock", "create_po_draft"}
    meta = card["metadata"]
    assert meta["side_effects"]["create_po_draft"] == "reversible_write"
    assert meta["owner"] and meta["stage"] == "prod"


def test_allowed_call_succeeds_and_is_audited(net):
    task = send(net, "sap-agent", "journey-agent", "get_stock", STOCK)
    assert task.status.state == "completed"
    assert task.artifact("stock")["on_hand"] == 600
    last = net.cp.audit[-1]
    assert (last["decision"], last["tenant"], last["caller"]) == (
        "allow",
        "northwind",
        "journey-agent",
    )
    assert last["traceparent"].startswith("00-")


def test_unregistered_caller_rejected(net):
    e = rejected(net, "sap-agent", "rogue-agent", "get_stock", STOCK)
    assert e.code == -32010 and "not registered" in e.reason
    assert net.cp.audit[-1]["decision"] == "deny"


def test_missing_caller_header_rejected(net):
    e = rejected(net, "sap-agent", None, "get_stock", STOCK)
    assert "not registered" in e.reason


def test_schema_rejection(net):
    e = rejected(net, "sap-agent", "journey-agent", "get_stock", {"sku": "200"})
    assert e.code == -32602 and "schema rejected" in e.reason
    e = rejected(net, "sap-agent", "journey-agent", "create_po_draft", {**DRAFT, "qty": -5})
    assert e.code == -32602


def test_policy_is_per_tenant(net):
    assert send(net, "sap-agent", "journey-agent", "create_po_draft", DRAFT).status.state == (
        "completed"
    )
    e = rejected(net, "sap-agent", "journey-agent", "create_po_draft", DRAFT, tenant="contoso")
    assert "tenant contoso" in e.reason


def test_marketing_agent_may_read_stock_but_not_write(net):
    assert send(net, "sap-agent", "marketing-agent", "get_stock", STOCK).status.state == (
        "completed"
    )
    e = rejected(net, "sap-agent", "marketing-agent", "create_po_draft", DRAFT)
    assert "may not use" in e.reason
    assert not net.services.erp.drafts


def test_caller_not_in_allowed_callers(net):
    e = rejected(
        net, "crm-agent", "marketing-agent", "get_customer_360", {"customer_id": "ACME-B2B"}
    )
    assert "not an allowed caller" in e.reason


def test_tenant_not_entitled(net):
    e = rejected(
        net,
        "demand-agent",
        "journey-agent",
        "forecast",
        {"sku": "SKU-200", "weeks": 4},
        tenant="umbrella",
    )
    assert "not entitled" in e.reason


def test_kill_switch_and_revive(net):
    net.cp.registry.kill("sap-agent", "incident INC-7")
    e = rejected(net, "sap-agent", "journey-agent", "get_stock", STOCK)
    assert e.code == -32011 and "INC-7" in e.reason
    net.cp.registry.revive("sap-agent")
    assert send(net, "sap-agent", "journey-agent", "get_stock", STOCK).status.state == ("completed")


def test_killed_caller_cannot_call(net):
    net.cp.registry.kill("journey-agent", "runaway loop")
    assert rejected(net, "sap-agent", "journey-agent", "get_stock", STOCK).code == -32011


def test_budget_exhausted(net):
    rec = net.cp.registry.get("demand-agent")
    net.cp.registry._agents["demand-agent"] = rec.model_copy(
        update={"budgets": Budgets(max_calls_per_caller=2)}
    )
    for _ in range(2):
        send(net, "demand-agent", "journey-agent", "forecast", FC)
    e = rejected(net, "demand-agent", "journey-agent", "forecast", FC)
    assert e.code == -32012


def _record(**kw):
    base = dict(
        name="pricing-agent",
        version="0.1.0",
        purpose="sets contract prices",
        owner="pricing",
        skills={"set_price": "irreversible_write"},
        tenants=["northwind"],
    )
    return AgentRecord(**(base | kw))


def test_promotion_gate_by_side_effect_class(net):
    reg = net.cp.registry
    reg.register(_record(eval_scores={"task_success": 0.91, "policy_violation_rate": 0.0}))
    with pytest.raises(RegistryError, match=r"irreversible_write bar 0\.95"):
        reg.promote("pricing-agent")
    reg.register(
        _record(
            name="faq-agent",
            skills={"answer": "read_only"},
            eval_scores={"task_success": 0.91, "policy_violation_rate": 0.0},
        )
    )
    assert reg.promote("faq-agent").stage == "prod"
    reg.register(
        _record(
            name="leaky-agent",
            skills={"answer": "read_only"},
            eval_scores={"task_success": 1.0, "policy_violation_rate": 0.01},
        )
    )
    with pytest.raises(RegistryError, match="policy_violation_rate"):
        reg.promote("leaky-agent")
    assert [e["event"] for e in reg.events].count("promotion_refused") == 2


def test_new_registrations_start_in_dev(net):
    with pytest.raises(RegistryError):
        net.cp.registry.register(_record(stage="prod"))


def test_unpromoted_callee_rejected(net):
    from control_plane.agents import build_network

    dev = build_network(promote=False)
    e = rejected(dev, "sap-agent", "journey-agent", "get_stock", STOCK)
    assert "not promoted" in e.reason
