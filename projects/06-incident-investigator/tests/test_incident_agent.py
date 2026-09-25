from langchain_core.messages import AIMessage
from langgraph.types import Command

from incident_agent.graph import RootCauseReport, build_graph
from incident_agent.llm import mock_investigator
from shared.llm import MockChatModel

CHECKOUT = {"id": "INC-1", "service": "checkout-api", "alert": "5xx > 5%"}
SEARCH = {"id": "INC-2", "service": "search-api", "alert": "p99 > 2s"}


def call(name, args, i=0):
    return AIMessage("", tool_calls=[{"name": name, "args": args, "id": f"x{i}"}])


def test_rollback_pauses_for_approval_then_mitigates(graph, systems, start):
    r, cfg = start(graph, CHECKOUT)
    req = r["__interrupt__"][0].value
    assert req["action"] == "rollback" and req["to_version"] == "v2.13.2"
    assert systems.deploys.rollbacks == []  # nothing written while paused
    r = graph.invoke(Command(resume={"approved": True, "approver": "sam"}), cfg)
    rep = RootCauseReport.model_validate(r["report"])
    assert rep.status == "mitigated" and "v2.14.0" in rep.root_cause
    assert systems.deploys.current["checkout-api"] == "v2.13.2"
    assert len(systems.deploys.rollbacks) == 1


def test_rejected_rollback_is_not_executed(graph, systems, start):
    _, cfg = start(graph, CHECKOUT)
    r = graph.invoke(Command(resume={"approved": False, "note": "hotfix instead"}), cfg)
    assert r["report"]["status"] == "mitigation_rejected"
    assert systems.deploys.rollbacks == []
    assert "REJECTED" in r["report"]["mitigation"]


def test_upstream_issue_diagnosed_without_write_action(graph, start):
    r, _ = start(graph, SEARCH)
    assert "__interrupt__" not in r
    rep = r["report"]
    assert rep["status"] == "diagnosed" and "propose_rollback" not in rep["tools_called"]
    assert "Elasticsearch" in rep["root_cause"]


def test_report_citations_must_reference_observed_evidence(graph, start):
    r, _ = start(graph, SEARCH)
    observed = {e for e in r["report"]["evidence"]}
    assert len(observed) >= 2 and all(e.startswith("EV-") for e in observed)


def test_fabricated_evidence_sends_report_to_human(systems, start):
    def fabricator(msgs):
        out = mock_investigator(msgs)
        if not out.tool_calls:  # final report: swap in made-up evidence ids
            return AIMessage(out.content.replace('"evidence": [', '"evidence": ["EV-fake-000", '))
        return out

    r, _ = start(build_graph(systems, llm=MockChatModel(responder=fabricator)), SEARCH)
    assert r["report"]["status"] == "needs_human"
    assert "EV-fake-000 was never observed" in r["report"]["problems"][0]


def test_max_steps_hard_stop(systems, start):
    counter = iter(range(1000))
    wanderer = MockChatModel(
        responder=lambda _: call(
            "recent_deploys", {"service": "checkout-api", "hours": next(counter)}
        )
    )
    r, _ = start(build_graph(systems, llm=wanderer, max_steps=4, max_tool_cost=999), CHECKOUT)
    rep = r["report"]
    assert rep["status"] == "incomplete" and rep["stop_reason"].startswith("max_steps")
    assert len(rep["tools_called"]) == 4


def test_max_tool_cost_hard_stop(systems, start):
    r, _ = start(build_graph(systems, max_tool_cost=6), CHECKOUT)
    rep = r["report"]
    assert rep["status"] == "incomplete" and rep["stop_reason"].startswith("max_tool_cost")
    assert rep["tool_cost"] >= 6 and "propose_rollback" not in rep["tools_called"]
    assert systems.deploys.rollbacks == []


def test_loop_detection_blocks_repeat_calls_and_stops(systems, start):
    stuck = MockChatModel(responder=lambda _: call("query_logs", {"service": "checkout-api"}))
    r, _ = start(build_graph(systems, llm=stuck), CHECKOUT)
    rep = r["report"]
    assert rep["status"] == "incomplete" and rep["stop_reason"].startswith("loop_detected")
    assert systems.tool_calls.count("query_logs") == 1  # repeats were never executed


def test_budget_blocks_individual_expensive_call(systems, start):
    greedy = iter(
        [
            call("query_logs", {"service": "checkout-api", "minutes": 1}, 0),
            call("query_logs", {"service": "checkout-api", "minutes": 2}, 1),
            AIMessage(
                '{"root_cause": "x", "summary": "y", "confidence": 0.1, "evidence": [], '
                '"mitigation": "none"}'
            ),
        ]
    )
    llm = MockChatModel(responder=lambda _: next(greedy))
    r, _ = start(build_graph(systems, llm=llm, max_tool_cost=5), CHECKOUT)
    assert systems.tool_calls.count("query_logs") == 1  # 2nd would exceed budget 5
    assert r["report"]["status"] == "needs_human"  # no valid evidence cited
