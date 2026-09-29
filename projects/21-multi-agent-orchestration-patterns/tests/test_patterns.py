"""Structural behaviour of each pattern on the shared loan-exception task."""

import pytest

from orchestration_lab import domain
from orchestration_lab.graph import PATTERNS
from orchestration_lab.harness import BOGUS_TARGET, FaultPlan
from orchestration_lab.patterns import group_chat

FLAWED = "L-2105"  # four conditions: the mock drafter's first draft omits one


def names(out):
    return [t["agent"] for t in out["turns"]]


def parallel_starts(out, *agents):
    starts = {t["agent"]: t["start_ms"] for t in out["turns"] if t["agent"] in agents}
    return len(set(starts.values())) == 1 and set(starts) == set(agents)


@pytest.mark.parametrize("pattern", sorted(PATTERNS))
def test_every_pattern_resolves_a_clean_case(run, pattern):
    out = run(pattern, "L-2101")
    r = out["result"]
    assert r["stop_reason"] == "completed"
    assert r["decision"] == "approve_with_conditions"
    assert domain.numbers_match(r["memo"], domain.LOANS["L-2101"])


def test_sequential_runs_fixed_order_and_cannot_revise(run):
    out = run("sequential", FLAWED)
    assert names(out) == ["researcher", "analyst", "policy", "drafter", "reviewer"]
    assert out["result"]["decision"] == "escalate"
    assert out["result"]["stop_reason"] == "review_failed"


def test_concurrent_fans_out_and_shortens_the_critical_path(run):
    seq, con = run("sequential", "L-2101"), run("concurrent", "L-2101")
    assert parallel_starts(con, "researcher", "policy", "analyst")
    assert con["clock_ms"] < seq["clock_ms"]
    assert con["ws"]["analysis"]["self_fetched"] is True
    assert con["tool_calls"] == 2 * seq["tool_calls"]  # the analyst reads the file itself


def test_supervisor_fans_out_independent_workers_then_revises(run):
    out = run("supervisor", FLAWED)
    assert names(out)[0] == "supervisor"
    assert parallel_starts(out, "researcher", "policy")
    assert [t["note"] for t in out["turns"] if t["agent"] == "drafter"] == ["draft r1", "draft r2"]
    assert out["result"]["stop_reason"] == "completed"


def test_supervisor_rejects_an_invalid_route(run):
    out = run("supervisor", "L-2101", faults=FaultPlan(bad_handoff=True))
    assert any(BOGUS_TARGET in e["reason"] and e["exit"] == "degrade" for e in out["exits"])
    assert BOGUS_TARGET not in names(out)
    assert out["result"]["stop_reason"] == "completed"


def test_supervisor_falls_back_on_unparseable_output(run):
    from langchain_core.messages import AIMessage

    from orchestration_lab import mock_llm
    from shared.llm import MockChatModel

    def garbled(msgs):
        if str(msgs[0].content).startswith("ROLE: supervisor"):
            return AIMessage("route to whoever, I am not sure")
        return mock_llm.respond(msgs)

    out = run("supervisor", "L-2101", llm=MockChatModel(responder=garbled))
    assert out["result"]["stop_reason"] == "completed"
    assert any("unparseable" in e["reason"] for e in out["exits"])


def test_hierarchical_uses_team_leads_and_parallel_teams(run):
    out = run("hierarchical", FLAWED)
    n = names(out)
    assert {
        "top_supervisor",
        "evidence_team.lead",
        "policy_team.lead",
        "decision_team.lead",
    } <= set(n)
    assert "supervisor" not in n
    ev = next(t for t in out["turns"] if t["agent"] == "evidence_team.lead")
    po = next(t for t in out["turns"] if t["agent"] == "policy_team.lead")
    assert ev["start_ms"] == po["start_ms"]  # both teams dispatched in one Send step
    assert out["result"]["stop_reason"] == "completed"


def test_swarm_has_no_router_turns_and_detects_ping_pong(run):
    ok = run("swarm", FLAWED)
    assert set(names(ok)) <= {"researcher", "analyst", "policy", "drafter", "reviewer"}
    assert ok["result"]["stop_reason"] == "completed"
    loop = run("swarm", "L-2101", faults=FaultPlan(loop=True))
    assert loop["result"]["stop_reason"] == "ping_pong_detected"
    # stopped before handing back to the reviewer a third time
    assert names(loop)[-5:] == ["drafter", "reviewer", "drafter", "reviewer", "drafter"]


def test_swarm_reasks_after_a_bad_handoff(run):
    out = run("swarm", "L-2101", faults=FaultPlan(bad_handoff=True))
    assert "researcher.handoff" in names(out)
    assert any(e["exit"] == "retry" for e in out["exits"])
    assert out["result"]["stop_reason"] == "completed"


def test_group_chat_debate_shares_the_transcript(run):
    out = run("group_chat", FLAWED)
    speakers = [m["speaker"] for m in out["transcript"]]
    assert speakers.count("advocate") == 2 and speakers.count("risk_officer") == 2
    first_ro = next(m for m in out["transcript"] if m["speaker"] == "risk_officer")
    assert first_ro["content"]["agree"] is False  # advocate opened with fewer conditions
    assert (
        out["ws"]["consensus"]["conditions"]
        == domain.decide(
            domain.LOANS[FLAWED], domain.rules_in_force(domain.as_of(domain.LOANS[FLAWED]))
        ).conditions
    )
    # everyone reads the whole transcript: later speakers pay for earlier ones
    drafter_tokens = [t["tokens"] for t in out["turns"] if t["agent"] == "drafter"]
    assert drafter_tokens[1] > drafter_tokens[0]
    assert out["result"]["stop_reason"] == "completed"


def test_group_chat_stops_at_max_rounds(run, monkeypatch):
    monkeypatch.setattr(group_chat, "MAX_ROUNDS", 5)
    out = run("group_chat", "L-2101")
    assert out["result"]["stop_reason"] == "max_rounds"
    assert out["result"]["decision"] == "escalate"


def test_magentic_keeps_ledgers_and_replans_around_a_failed_worker(run):
    out = run("magentic", "L-2101", faults=FaultPlan(down="analyst"))
    n = names(out)
    assert n[0] == "manager.plan" and "manager.replan" in n
    assert out["ws"]["analysis"]["by"] == "researcher"
    assert out["control"]["ledger"]["plan"][1] == {"task": "analysis", "agent": "researcher"}
    assert out["result"]["stop_reason"] == "completed"


def test_magentic_stall_detection_ends_a_loop(run):
    out = run("magentic", "L-2101", faults=FaultPlan(loop=True))
    assert out["result"]["stop_reason"] == "stalled"
    assert names(out).count("manager.replan") == 1


def test_blackboard_fires_eligible_sources_in_parallel(run):
    out = run("blackboard", "L-2101")
    assert names(out)[:2] == ["researcher", "policy"] or names(out)[:2] == ["policy", "researcher"]
    assert parallel_starts(out, "researcher", "policy")
    assert out["llm_calls"] == 4  # no routing model at all


def test_blackboard_capability_fallback_and_no_progress(run):
    down = run("blackboard", "L-2101", faults=FaultPlan(down="analyst"))
    assert "researcher.analysis" in names(down)
    assert down["result"]["stop_reason"] == "completed"
    loop = run("blackboard", "L-2101", faults=FaultPlan(loop=True))
    assert loop["result"]["stop_reason"] == "no_progress"


@pytest.mark.parametrize(
    "pattern", ["sequential", "concurrent", "supervisor", "hierarchical", "swarm", "group_chat"]
)
def test_worker_down_is_a_safe_stop(run, pattern):
    out = run(pattern, "L-2101", faults=FaultPlan(down="analyst"))
    assert out["result"]["decision"] == "escalate"
    assert out["result"]["stop_reason"] == "worker_failed:analyst"
    assert out["result"]["memo"] == ""
