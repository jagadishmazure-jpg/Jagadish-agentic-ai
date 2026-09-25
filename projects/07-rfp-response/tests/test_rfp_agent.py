import json

from rfp_agent.graph import MAX_REVISIONS, ResponseDoc, build_graph
from rfp_agent.knowledge import RFP
from rfp_agent.llm import mock_responder
from rfp_agent.rules import compliance_scan, critique
from shared.llm import MockChatModel


def by_id(result):
    return {a["id"]: a for a in result["final_answers"]}


def test_planner_splits_sections_and_every_question_is_answered_once(result):
    assert [s["name"] for s in result["sections"]] == [
        "Security",
        "Compliance",
        "Operations",
        "Legal",
    ]
    ids = [a["id"] for a in result["final_answers"]]
    assert ids == [f"Q{i}" for i in range(1, 10)]  # all sections merged, ordered


def test_sections_processed_by_worker_subgraph_via_send(result):
    sections = {a["section"] for a in result["answers"]}
    assert sections == {"Security", "Compliance", "Operations", "Legal"}


def test_critic_loop_revises_incomplete_draft(result):
    q1 = by_id(result)["Q1"]
    assert q1["status"] == "accepted" and q1["attempts"] == 2
    assert q1["citations"] == ["KB-SEC-001", "KB-SEC-002"]
    assert "in transit" in q1["answer"] and "at rest" in q1["answer"]


def test_retry_budget_then_escalate_to_sme():
    def stubborn(msgs):
        if str(msgs[0].content).startswith("TASK: DRAFT"):
            payload = json.loads(msgs[-1].content)
            if payload["kb"]:
                return f"Data is encrypted at rest [{payload['kb'][0]['id']}]."
        return mock_responder(msgs)

    r = build_graph(llm=MockChatModel(responder=stubborn)).invoke({"rfp_text": RFP})
    q1 = by_id(r)["Q1"]
    assert q1["status"] == "needs_sme" and q1["attempts"] == MAX_REVISIONS + 1
    assert "does not address" in q1["issues"][0]


def test_question_without_kb_coverage_goes_to_sme_without_retries(result):
    q8 = by_id(result)["Q8"]
    assert q8["status"] == "needs_sme" and q8["attempts"] == 1 and q8["answer"] == ""


def test_every_accepted_answer_cites_kb(result):
    for a in result["final_answers"]:
        if a["status"] == "accepted":
            assert a["citations"] and all(c.startswith("KB-") for c in a["citations"])


def test_critic_rejects_invented_citations():
    issues = critique("What uptime SLA?", "99.99% uptime [KB-OPS-009].", ["KB-OPS-001"])
    assert any("not in retrieved" in i for i in issues)


def test_compliance_strips_banned_claims_but_keeps_cited_rest(result):
    q3 = by_id(result)["Q3"]
    assert "never been breached" not in q3["answer"]
    assert q3["compliance_removed"] and q3["status"] == "accepted"
    assert q3["citations"] == ["KB-SEC-004"]
    assert any("Q3" in r for r in result["document"]["banned_claims_removed"])


def test_export_control_terms_require_legal_review(result):
    doc = ResponseDoc.model_validate(result["document"])
    assert doc.status == "legal_review_required"
    assert "ITAR" in doc.export_control_hits
    assert "🔒 Legal review" in doc.markdown


def test_clean_rfp_is_ready():
    rfp = "# RFP-X\n\n## Ops\nQ1. What uptime SLA do you offer?\nQ2. What are your RPO and RTO?\n"
    doc = build_graph().invoke({"rfp_text": rfp})["document"]
    assert doc["status"] == "ready" and doc["answered"] == 2 and doc["needs_sme"] == []


def test_planner_falls_back_to_deterministic_parse_on_bad_llm_output():
    def bad_planner(msgs):
        if str(msgs[0].content).startswith("TASK: PLAN"):
            return "Sure! Here are the sections: security, compliance..."
        return mock_responder(msgs)

    r = build_graph(llm=MockChatModel(responder=bad_planner)).invoke({"rfp_text": RFP})
    assert len(r["sections"]) == 4 and len(r["final_answers"]) == 9


def test_compliance_scan_unit():
    text, removed, export = compliance_scan("Fast. We offer military-grade security. EAR99.")
    assert "military" not in text and len(removed) == 1 and export == []
    assert compliance_scan("Shipping to Iran is prohibited.")[2] == ["Iran"]
