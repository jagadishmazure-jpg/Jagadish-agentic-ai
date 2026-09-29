"""Harness: budgets, loop detection, route validation, critical-path clock, OTel spans."""

from orchestration_lab.harness import Budgets, FaultPlan, Harness
from shared.observability import telemetry


def test_turn_budget_stops_a_run(run):
    out = run("supervisor", "L-2101", budgets=Budgets(max_turns=4))
    assert out["result"]["stop_reason"] == "budget_exhausted:turns"
    assert out["result"]["decision"] == "escalate"


def test_token_budget_stops_a_group_chat(run):
    out = run("group_chat", "L-2105", budgets=Budgets(max_tokens=2_000))
    assert out["result"]["stop_reason"] == "budget_exhausted:tokens"
    assert out["tokens"] < 2_000 + 1_000  # stops within one turn of the budget


def test_llm_call_budget(run):
    out = run("magentic", "L-2101", budgets=Budgets(max_llm_calls=5))
    assert out["result"]["stop_reason"] == "budget_exhausted:llm_calls"


def test_ping_pong_detector():
    t = [{"agent": a} for a in ["x", "drafter", "reviewer"] * 1 + ["drafter", "reviewer"] * 2]
    assert Harness.ping_pong(t)
    assert not Harness.ping_pong(t[:-1])
    assert not Harness.ping_pong([{"agent": "a"}] * 6)  # one agent repeating is not ping-pong


def test_route_validation_rejects_unregistered_targets():
    assert Harness.valid_target("drafter", {"drafter", "reviewer"})
    assert not Harness.valid_target("funds_disbursement_agent", {"funds_disbursement_agent"})
    assert not Harness.valid_target("reviewer", {"drafter"})


def test_bad_handoff_fault_fires_once():
    h = Harness("swarm", faults=FaultPlan(bad_handoff=True))
    assert h.propose("analyst") != "analyst"
    assert h.propose("analyst") == "analyst"
    assert Harness("swarm").propose("FINISH") == "FINISH"


def test_clock_reports_critical_path_not_sum(run):
    out = run("concurrent", "L-2101")
    total = sum(t["ms"] for t in out["turns"])
    assert out["clock_ms"] < total
    branch_end = max(t["start_ms"] + t["ms"] for t in out["turns"][:3])
    drafter = next(t for t in out["turns"] if t["agent"] == "drafter")
    assert drafter["start_ms"] >= branch_end  # fan-in waits for the slowest branch


def test_every_agent_turn_emits_a_span(run):
    exporter = telemetry().exporter
    out = run("hierarchical", "L-2101")
    spans = [s for s in exporter.spans if s.name.startswith("agent ")]
    mine = [s for s in spans if s.attributes.get("orchestration.pattern") == "hierarchical"]
    run_ids = {s.attributes["orchestration.run_id"] for s in mine}
    latest = [s for s in mine if s.attributes["orchestration.run_id"] == sorted(run_ids)[-1]]
    assert latest or mine
    by_run: dict[str, list[str]] = {}
    for s in mine:
        by_run.setdefault(s.attributes["orchestration.run_id"], []).append(
            s.attributes["agent.name"]
        )
    turn_names = sorted(t["agent"] for t in out["turns"])
    assert any(sorted(v) == turn_names for v in by_run.values())
    one = next(s for s in mine if s.attributes["agent.name"] == "policy")
    assert one.attributes["llm.calls"] == 1 and one.attributes["sim.latency_ms"] > 0


def test_model_down_takes_deterministic_paths(run, kill_model):
    for pattern in ("supervisor", "swarm", "magentic", "group_chat", "hierarchical"):
        out = run(pattern, "L-2105")
        assert out["llm_calls"] == 0
        assert out["result"]["stop_reason"] == "completed", pattern
        assert any(e["exit"] == "degrade" for e in out["exits"])
