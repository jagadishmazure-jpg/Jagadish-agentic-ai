from datetime import date, datetime

from langgraph.types import Command

from care_e2e import knowledge
from care_e2e.graph import build_graph, sweep_expired
from care_e2e.worker import drain
from shared import faults

LATE = "My shipment {} is late, can I get a refund?"


def test_happy_path_runs_all_lanes_and_pays_once(graph, ask, systems):
    r, _ = ask(graph, LATE.format("O-1001"))
    assert r["trace"][:3] == ["classify", "plan", "order"]
    assert {"policy", "history"} <= set(r["trace"])
    assert r["outcome"] == "refund_issued" and r["proposal"]["amount"] == 48.99
    assert "[CARE-LATE-2026]" in r["reply"] and "confirmed refund R-" in r["reply"]
    assert len(systems.payments.refunds) == 1
    assert systems.orders["O-1001"]["refund_id"]  # OMS follow-up via outbox worker


def test_policy_is_retrieved_as_of_purchase_date_not_today(graph, ask):
    r, _ = ask(graph, LATE.format("O-1004"))
    assert r["policy"]["edition"] == "CARE-LATE-2025" and r["policy"]["as_of"] == "2025-12-10"
    assert r["proposal"]["amount"] == 6.99  # the 2026 edition would have refunded in full


def test_acl_trims_fraud_playbook_and_billing_only_cases(graph, ask):
    r, _ = ask(graph, LATE.format("O-1001"))
    assert "CARE-FRAUD-INT" not in r["citations"]
    assert r["policy"]["dropped_acl"] >= 1
    assert [h["case_id"] for h in r["history"]] == ["CASE-11"]  # CASE-12 is billing-only


def test_other_tenant_sees_no_cases():
    who = knowledge.principal("globex")
    chunks = knowledge.case_chunks(
        [
            {
                "case_id": "X",
                "at": "2026-01-01",
                "text": "t",
                "groups": ["care"],
                "tenant": "acme-retail",
            }
        ]
    )
    assert not chunks[0].visible_to(who)


def test_fraud_pre_route_never_reaches_refund_tools(graph, ask, systems):
    r, _ = ask(graph, LATE.format("O-3001"), customer="C300", email="cy@example.com")
    assert r["outcome"] == "handoff_specialist" and "refund" not in r["trace"]
    assert "fraud" not in r["reply"].lower() and not systems.payments.refunds


def test_confidence_gate_asks_for_clarification(graph, ask):
    r, _ = ask(graph, "refund please")
    assert r["outcome"] == "clarify" and r["trace"] == ["classify", "handoff"]


def test_large_refund_hitl_approve_and_agent_cannot_approve(graph, ask, systems):
    r, cfg = ask(graph, LATE.format("O-1005"))
    payload = r["__interrupt__"][0].value
    assert payload["proposal"]["amount"] == 249.0 and payload["sla_due"]
    r = graph.invoke(Command(resume={"decision": "approve", "approver": "mi-care-agent"}), cfg)
    assert r["outcome"] == "denied" and not systems.payments.refunds


def test_sla_timeout_queues_and_never_pays(graph, ask, systems):
    _, cfg = ask(graph, LATE.format("O-1005"))
    assert sweep_expired(graph, systems, datetime(2026, 9, 25, 15)) == []  # not yet due
    assert sweep_expired(graph, systems, datetime(2026, 9, 25, 19)) == [
        cfg["configurable"]["thread_id"]
    ]
    st = graph.get_state(cfg).values
    assert st["outcome"] == "queued_for_review" and not systems.payments.refunds
    assert "No refund has been issued yet" in st["reply"]


def test_timeout_policy_deny(systems, ask):
    g = build_graph(systems, timeout_policy="deny")
    _, cfg = ask(g, LATE.format("O-1005"))
    sweep_expired(g, systems, datetime(2026, 9, 26))
    assert g.get_state(cfg).values["outcome"] == "denied" and not systems.payments.refunds


def test_payments_down_queues_then_worker_redelivers_once(graph, ask, systems):
    faults.inject("sor:payments")
    r, _ = ask(graph, LATE.format("O-1001"))
    faults.clear("sor:payments")
    assert r["outcome"] == "refund_queued" and "CS-1001" in r["reply"]
    assert "hasn't confirmed" in r["reply"]
    from care_e2e.sor import build_gateways

    assert drain(systems, build_gateways(systems)["writer"]) == 1
    assert drain(systems, build_gateways(systems)["writer"]) == 0
    assert len(systems.payments.refunds) == 1


def test_critic_repairs_once_then_escalates(systems, ask):
    from care_e2e import llm as ops
    from shared.llm import MockChatModel

    g = build_graph(systems, llm=MockChatModel(responder=ops.sloppy_responder))
    r, _ = ask(g, LATE.format("O-1001"))
    assert r["outcome"] == "refund_issued" and r["critic"]["repairs"] == 1
    g = build_graph(systems, llm=MockChatModel(responder=ops.stubborn_responder))
    r, _ = ask(g, LATE.format("O-1002"))
    assert "__interrupt__" in r
    assert any(x.startswith("critic:") for x in r["__interrupt__"][0].value["reasons"])


def test_planner_budget_is_enforced(systems, ask):
    from care_e2e import llm as ops
    from shared.llm import MockChatModel

    def stingy(msgs):
        if str(msgs[0].content).startswith("TASK: PLAN"):
            return '{"lanes": ["policy"], "max_tool_calls": 2, "reason": "cheap"}'
        return ops.mock_responder(msgs)

    g = build_graph(systems, llm=MockChatModel(responder=stingy))
    r, _ = ask(g, LATE.format("O-1001"))
    assert r["outcome"] == "escalated" and ("order", "escalate") in [
        (e["node"], e["exit"]) for e in r["exits"]
    ]


def test_invalid_plan_without_policy_lane_is_guarded(systems, ask):
    from care_e2e import llm as ops
    from shared.llm import MockChatModel

    def rogue(msgs):
        if str(msgs[0].content).startswith("TASK: PLAN"):
            return '{"lanes": ["history"], "max_tool_calls": 8, "reason": "skip policy"}'
        return ops.mock_responder(msgs)

    r, _ = ask(build_graph(systems, llm=MockChatModel(responder=rogue)), LATE.format("O-1001"))
    assert "policy" in r["trace"] and r["outcome"] == "refund_issued"


def test_temporal_filter_directly():
    kb = knowledge.builder()
    b = kb.build(
        "late delivery refund",
        knowledge.principal("acme-retail"),
        as_of=date(2025, 6, 1),
        kinds=["policy"],
    )
    assert "CARE-LATE-2026::1" not in b.chunk_ids and b.dropped_temporal >= 1
