from datetime import UTC, datetime

import pytest
from langgraph.types import Command

from collections_agent.audit import AuditLog, mask
from collections_agent.graph import build_graph
from collections_agent.llm import mock_responder
from collections_agent.policy import DISCLOSURE, check_plan, contact_decision
from collections_agent.registry import PermissionDenied
from collections_agent.systems import seed_systems
from shared.llm import MockChatModel

LATE_NIGHT = datetime(2026, 9, 26, 3, 30, tzinfo=UTC)  # 22:30 America/Chicago


def _run(acct, systems=None, llm=None, resume=None):
    systems = systems or seed_systems()
    graph = build_graph(systems, llm=llm)
    cfg = {"configurable": {"thread_id": acct}}
    r = graph.invoke({"account_id": acct}, cfg)
    if resume is not None:
        assert "__interrupt__" in r
        r = graph.invoke(Command(resume=resume), cfg)
    return r, systems, graph, cfg


def test_least_privilege_scopes_and_denials_are_audited():
    s = seed_systems()
    reg = s.registry
    assert reg.tools_for("collections-reader") == ["get_account", "get_contact_history"]
    assert reg.tools_for("plan-writer") == ["create_payment_plan"]
    assert reg.tools_for("outreach-sender") == ["send_message"]
    with pytest.raises(PermissionDenied):
        reg.client("collections-reader").call(
            "send_message", account_id="A-1001", channel="email", body="hi"
        )
    with pytest.raises(PermissionDenied):
        reg.client("plan-proposer").call(
            "create_payment_plan",
            account_id="A-1001",
            plan={},
            approved_by="x",
            idempotency_key="k",
        )
    with pytest.raises(PermissionDenied):
        reg.client("outreach-sender").call("get_account", account_id="A-1001")
    assert s.audit.actions().count("permission_denied") == 3
    assert not s.outbox and not s.plans


def test_happy_path_requires_human_approval_then_writes_with_write_identities():
    r, s, _, _ = _run("A-1001")
    assert r["decision"] == "allowed" and "__interrupt__" in r
    req = r["__interrupt__"][0].value
    assert req["account"]["name"] == "M***" and req["account"]["email"] == "[REDACTED]"
    assert not s.plans and not s.outbox  # nothing written before approval
    r, s, _, _ = _run("A-1001", resume={"decision": "approve", "reviewer": "j.meduri"})
    assert r["outcome"] == "plan_created_message_sent"
    assert r["plan_record"]["approved_by"] == "j.meduri" and r["plan"]["installment"] == 200.0
    assert DISCLOSURE in s.outbox[0]["body"]
    writers = {e["actor"] for e in s.audit.entries if e["details"].get("write")}
    assert writers == {"plan-writer", "outreach-sender"}


def test_reject_and_separation_of_duties():
    r, s, _, _ = _run("A-1001", resume={"decision": "reject", "reviewer": "j.meduri"})
    assert r["outcome"] == "rejected" and not s.plans and not s.outbox
    r, s, _, _ = _run("A-1001", resume={"decision": "approve", "reviewer": "plan-proposer"})
    assert r["outcome"] == "rejected" and not s.plans
    r, s, _, _ = _run("A-1001", resume={"decision": "approve"})
    assert r["outcome"] == "rejected"


@pytest.mark.parametrize(
    ("acct", "decision", "outcome"),
    [
        ("A-1002", "hardship", "hardship_referral"),
        ("A-1003", "no_contact", "no_contact"),
        ("A-1005", "no_contact", "no_contact"),
        ("A-1004", "defer", "deferred"),
    ],
)
def test_policy_branches_never_reach_writers(acct, decision, outcome):
    r, s, _, _ = _run(acct)
    assert r["decision"] == decision and r["outcome"] == outcome
    assert "__interrupt__" not in r and not s.outbox and not s.plans
    assert r["audit_ok"]


def test_contact_hours_rule_and_send_time_recheck():
    s = seed_systems(now=LATE_NIGHT)
    r, *_ = _run("A-1001", systems=s)
    assert r["outcome"] == "deferred" and "outside allowed hours" in r["reasons"][0]
    assert r["next_allowed"] == "2026-09-26T08:00:00-05:00"
    # Approved during hours, but the reviewer took until 22:30 -> plan created, message deferred.
    s = seed_systems()
    graph = build_graph(s)
    cfg = {"configurable": {"thread_id": "t"}}
    graph.invoke({"account_id": "A-1001"}, cfg)
    s.now = LATE_NIGHT
    r = graph.invoke(Command(resume={"decision": "approve", "reviewer": "j.meduri"}), cfg)
    assert r["outcome"] == "plan_created_message_deferred" and s.plans and not s.outbox


def test_plan_policy_clamps_llm_overreach_and_message_guard():
    def rogue(messages):
        sys = str(messages[0].content)
        if sys.startswith("TASK: PROPOSE_PLAN"):
            return '{"months": 36, "discount_pct": 40, "rationale": "be generous"}'
        if sys.startswith("TASK: DRAFT_MESSAGE"):
            return "Pay now or we will file a lawsuit and tell your employer."
        return mock_responder(messages)

    r, *_ = _run("A-1001", llm=MockChatModel(responder=rogue))
    req = r["__interrupt__"][0].value
    assert req["plan"]["months"] == 12 and req["plan"]["discount_pct"] == 10.0
    assert len(req["policy_violations_clamped"]) == 2
    assert req["message_issues_replaced"] and "lawsuit" not in req["draft_message"]
    assert DISCLOSURE in req["draft_message"]
    assert check_plan({"months": 12}, 100.0)[0]["months"] == 4  # $25 minimum installment


def test_audit_hash_chain_detects_tampering_and_masks_pii():
    _, s, *_ = _run("A-1001", resume={"decision": "approve", "reviewer": "j.meduri"})
    ok, bad = s.audit.verify()
    assert ok and bad is None
    blob = str(s.audit.entries)
    for secret in ("maria.lopez@example.com", "Maria", "004417755"):
        assert secret not in blob
    send = next(e for e in s.audit.entries if e["action"] == "tool:send_message")
    assert send["details"]["args"]["body"].startswith("sha256:")
    s.audit.entries[5]["details"]["decision"] = "reject"  # edit history
    assert s.audit.verify() == (False, 6)
    s.audit.entries[5]["details"]["decision"] = "approve"
    del s.audit.entries[2]  # delete an entry
    assert s.audit.verify()[0] is False


def test_mask_and_idempotent_plan_write():
    assert mask({"note": "call +1 312 555 0147 or mail a.b@x.com re ACCT-004417755"}) == {
        "note": "call ***-***-0147 or mail a***@x.com re ****7755"
    }
    log = AuditLog()
    log.record("a", "x", "t", name="Maria Lopez")
    assert log.entries[0]["details"]["name"] == "M***"
    s = seed_systems()
    w = s.registry.client("plan-writer")
    a = w.call(
        "create_payment_plan",
        account_id="A-1001",
        plan={"months": 6},
        approved_by="j",
        idempotency_key="k1",
    )
    b = w.call(
        "create_payment_plan",
        account_id="A-1001",
        plan={"months": 6},
        approved_by="j",
        idempotency_key="k1",
    )
    assert a["plan_id"] == b["plan_id"] and b["duplicate"] and len(s.plans) == 1


def test_contact_frequency_cap_counts_only_last_7_days():
    s = seed_systems()
    acct = s.accounts["A-1004"]
    now = s.now
    assert contact_decision(acct, s.history["A-1004"], now)[0] == "defer"
    assert contact_decision(acct, s.history["A-1004"][:6], now)[0] == "allowed"
