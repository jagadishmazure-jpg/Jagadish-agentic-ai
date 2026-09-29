"""Arena graph: intake, HITL gate, filing, ACL and as-of policy retrieval."""

from langgraph.types import Command

from orchestration_lab import domain, knowledge
from orchestration_lab.graph import PATTERNS, build_graph


def test_arena_nodes_cover_every_pattern():
    nodes = {n for n in build_graph().get_graph().nodes if not n.startswith("__")}
    assert nodes == {"intake", "human_gate", "finalize", *PATTERNS}


def test_referral_pauses_for_a_credit_officer_and_resumes(arena):
    g, systems, cfg = arena(hitl=True)
    r = g.invoke({"loan_id": "L-2103", "pattern": "swarm"}, cfg)
    ask = r["__interrupt__"][0].value
    assert ask["loan_id"] == "L-2103" and "CP-DTI-2026" in ask["memo"]
    assert not systems.filed  # nothing filed while waiting
    r = g.invoke(Command(resume={"decision": "decline", "approver": "co-7"}), cfg)
    assert r["final"]["decision"] == "decline" and r["final"]["decided_by"] == "co-7"
    assert len(systems.filed) == 1


def test_safety_stop_also_goes_to_the_human_gate(arena):
    from orchestration_lab.harness import FaultPlan

    g, _systems, cfg = arena(hitl=True, faults=FaultPlan(down="analyst"))
    r = g.invoke({"loan_id": "L-2101", "pattern": "sequential"}, cfg)
    assert r["__interrupt__"][0].value["reason"] == "worker_failed:analyst"


def test_completed_memo_is_filed_once_by_the_orchestrator(arena):
    g, systems, cfg = arena(hitl=False)
    r = g.invoke({"loan_id": "L-2102", "pattern": "blackboard"}, cfg)
    assert r["final"]["filed"]["filed"] is True
    assert systems.filed == [
        {"loan_id": "L-2102", "decision": "approve_with_conditions", "memo": r["final"]["memo"]}
    ]


def test_no_worker_identity_can_file(arena):
    import pytest

    from orchestration_lab.sor import LoanSystems, gateways
    from shared.tools import ToolDeniedError

    gws = gateways(LoanSystems())
    for name in ("researcher", "analyst"):
        with pytest.raises(ToolDeniedError):
            gws[name].call(
                "loan_system",
                "file_exception_memo",
                loan_id="L-2101",
                decision="approve",
                memo="x",
                idempotency_key="k",
                dry_run=False,
            )


def test_unknown_loan_is_rejected_at_intake(arena):
    g, _, cfg = arena(hitl=False)
    r = g.invoke({"loan_id": "L-0000", "pattern": "supervisor"}, cfg)
    assert r["final"]["decision"] == "rejected"
    assert ("intake", "escalate") in [(e["node"], e["exit"]) for e in r["exits"]]


def test_policy_retrieval_is_as_of_the_application_date(run):
    old = run("supervisor", "L-2109")  # applied 2025-11-14: 2025 DTI edition (ceiling 48%)
    assert old["ws"]["rules"]["dti"] == "CP-DTI-2025"
    assert old["result"]["decision"] == "escalate"
    new = run("supervisor", "L-2101")
    assert new["ws"]["rules"]["dti"] == "CP-DTI-2026"


def test_restricted_minutes_are_never_retrievable():
    b = knowledge.builder()
    bundle = b.build("credit committee minutes referred files", knowledge.principal(), k=10)
    assert all(h.chunk.doc_id != "CC-MINUTES-2026-03" for h in bundle.hits)
    assert bundle.dropped_acl >= 1


def test_decision_rule_matches_golden_expectations():
    import json
    from pathlib import Path

    golden = Path(__file__).resolve().parents[1] / "evals" / "golden.jsonl"
    for line in golden.read_text().splitlines():
        case = json.loads(line)
        if "business" not in case.get("tags", []):
            continue
        f = domain.LOANS[case["input"]["loan_id"]]
        d = domain.decide(f, domain.rules_in_force(domain.as_of(f)))
        assert d.decision == case["expect"]["decision"], case["id"]
        assert sorted(d.conditions) == sorted(case["expect"]["conditions"]), case["id"]
