"""Credit memo: semantic layer (no SQL, dry-run), ownership over time, ML tool, citations,
dual control, fallback model cannot skip KYC."""

from datetime import date

import pytest
from langgraph.types import Command

from credit_memo import semantic
from credit_memo.eval_suite import CHECKER, MAKER, request, run
from credit_memo.graph import build_graph, fast_track_responder, numbers
from credit_memo.ownership import beneficial_owners
from credit_memo.systems import seed_systems
from shared import faults
from shared.llm import MockChatModel


def test_semantic_layer_rejects_anything_but_governed_measures():
    with pytest.raises(semantic.SemanticError, match="unknown measure"):
        semantic.get_measure("SELECT * FROM loans", "year", {"borrower_id": "B-100"})
    with pytest.raises(semantic.SemanticError, match="mandatory"):
        semantic.get_measure("revenue", "year", {})
    with pytest.raises(semantic.SemanticError, match="no SQL"):
        semantic.get_measure("revenue", "year", {"borrower_id": "B-100' OR 1=1 --"})
    with pytest.raises(semantic.SemanticError, match="grain"):
        semantic.get_measure("revenue", "day", {"borrower_id": "B-100"})
    with pytest.raises(semantic.SemanticError, match="filter keys"):
        semantic.get_measure("revenue", "year", {"borrower_id": "B-100", "sql": "x"})


def test_dry_run_returns_plan_without_values():
    out = semantic.get_measure("leverage", "year", {"borrower_id": "B-100", "year": [2025]})
    assert out["plan"]["expression"] == "total_debt / ebitda" and "values" not in out
    assert out["plan"]["estimated_rows"] == 1


def test_graph_dry_runs_before_executing():
    r, _ = run({})
    assert len(r["measure_plans"]) == 4
    assert all(p["filters"]["borrower_id"] == "B-100" for p in r["measure_plans"])
    assert r["financials"]["leverage"]["2025"] == 2.75


def test_ownership_changes_over_time():
    before = beneficial_owners("B-100", date(2025, 6, 1))["ubos"]
    after = beneficial_owners("B-100", date(2026, 6, 1))["ubos"]
    assert before == {"Jane Park": 0.48, "Marcus Lee": 0.32}
    assert after == {"Marcus Lee": 0.56}
    assert beneficial_owners("B-200", date(2026, 6, 1))["opaque"]


def test_risk_score_comes_from_the_model_tool():
    r, _ = run({})
    assert r["risk"] == {"pd": 0.011, "grade": "BB+", "model_version": "pd-scorecard-2026.03"}
    assert "PD 0.011 [RISK:score]" in r["memo"]


def test_memo_cites_governed_sources():
    r, _ = run({})
    assert {
        "M:leverage:2025",
        "M:dscr:2025",
        "RISK:score",
        "CP-LEVERAGE-2026::1",
        "OWN::e6",
    } <= set(r["citations"])


def test_critic_replaces_invented_numbers():
    def inventive(msgs):
        if "TASK: MEMO" in str(msgs[0].content):
            return "Leverage is a comfortable 1.9x [M:leverage:2025]. Approve."
        return fast_track_responder(msgs) if "PLAN" in str(msgs[0].content) else ""

    s = seed_systems()
    g = build_graph(s, llm=MockChatModel(responder=inventive))
    r = g.invoke({"request": request()}, {"configurable": {"thread_id": "inv"}})
    assert "1.9" not in r["memo"] and "2.75x" in r["memo"]
    assert numbers("x 1,000.5 [M:a:2025]") == {"1000.5"}


def test_dual_control_enforced_in_graph_and_in_system():
    r, s = run({"approvals": [MAKER, {"approver": "rm-diaz", "decision": "approve"}]})
    assert r["status"] == "dual_control_refused" and not s.limits
    with pytest.raises(PermissionError):
        s.set_credit_limit("B-100", 1.0, ["co-nguyen", "co-nguyen"])
    with pytest.raises(PermissionError):
        s.set_credit_limit("B-100", 1.0, ["co-nguyen", "rm-diaz"])


def test_booking_idempotent_on_replay():
    s = seed_systems()
    g = build_graph(s)
    req = request()
    for t in ("x", "y"):
        cfg = {"configurable": {"thread_id": t}}
        g.invoke({"request": req}, cfg)
        g.invoke(Command(resume=MAKER), cfg)
        g.invoke(Command(resume=CHECKER), cfg)
    assert len(s.limits) == 1


def test_fallback_model_cannot_skip_kyc():
    s = seed_systems()
    g = build_graph(s, fallback_llm=MockChatModel(responder=fast_track_responder))
    with faults.fault("model:primary"):
        r = g.invoke({"request": request("B-200")}, {"configurable": {"thread_id": "fb"}})
    assert "kyc" in r["trace"] and r["status"] == "kyc_incomplete"
    assert any("omitted ['kyc'" in e["reason"] for e in r["exits"])
    assert not r.get("memo")
