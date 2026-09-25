import json

import pytest

from contract_review.contracts import DEMO, EVAL_SET
from contract_review.evaluation import gate, run_eval
from contract_review.graph import MAX_ITERATIONS, ReviewReport, build_graph
from contract_review.library import DISCLAIMER
from contract_review.llm import mock_responder
from contract_review.rules import segment
from shared.llm import MockChatModel


def review(text=DEMO, responder=mock_responder):
    return build_graph(llm=MockChatModel(responder=responder)).invoke({"text": text})


def findings(r):
    return {f["clause_type"]: f for f in r["report"]["findings"]}


def test_segmentation_and_classification():
    assert [c["id"] for c in segment(DEMO)] == [f"§{i}" for i in range(1, 8)]
    r = review()
    types = [c["type"] for c in r["clauses"]]
    assert types == [
        "payment_terms",
        "auto_renewal",
        "termination",
        "limitation_of_liability",
        "indemnification",
        "confidentiality",
        "governing_law",
    ]


def test_evaluator_feedback_drives_one_revision_to_pass():
    r = review()
    assert len(r["history"]) == 2
    assert len(r["history"][0]["feedback"]) > 0 and r["history"][1]["feedback"] == []
    rep = ReviewReport.model_validate(r["report"])
    assert rep.evaluation_passed and rep.iterations == 2
    assert all(f.source == "optimizer" for f in rep.findings)


def test_severity_scoring_and_legal_routing():
    rep = review()["report"]
    f = findings({"report": rep})
    assert f["limitation_of_liability"]["severity"] == "critical"
    assert rep["risk_tier"] == "high" and rep["route"] == "legal_review_required"
    assert rep["findings"][0]["severity"] == "critical"  # sorted by severity
    assert rep["disclaimer"] == DISCLAIMER


def test_missing_required_clause_is_flagged_only_when_applicable():
    assert findings(review())["data_protection"]["clause_id"] is None
    nda = next(c for c in EVAL_SET if c["id"] == "EV5-nda")["text"]
    rep = review(nda)["report"]
    assert rep["findings"] == [] and rep["route"] == "business_owner_review"
    assert rep["risk_tier"] == "low"


def test_budget_exhausted_then_guardrails_enforce_playbook_floor():
    def stubborn(msgs):  # never improves: medium severity, generic redlines
        if str(msgs[0].content).startswith("TASK: REVIEW"):
            payload = json.loads(msgs[-1].content)
            payload["feedback"], payload["previous_findings"] = [], []
            return mock_responder([msgs[0], type(msgs[-1])(json.dumps(payload))])
        return mock_responder(msgs)

    r = review(responder=stubborn)
    rep = r["report"]
    assert rep["iterations"] == MAX_ITERATIONS and not rep["evaluation_passed"]
    assert rep["unresolved_feedback"]
    f = findings(r)
    assert f["limitation_of_liability"]["severity"] == "critical"
    assert f["limitation_of_liability"]["source"] == "evaluator_enforced"
    assert "12 months" in f["limitation_of_liability"]["redline"]
    assert f["data_protection"]["source"] == "evaluator_enforced"


def test_unsupported_findings_are_dropped():
    def hallucinator(msgs):
        out = json.loads(mock_responder(msgs)) if "REVIEW" in str(msgs[0].content) else None
        if out is None:
            return mock_responder(msgs)
        out["findings"].append(
            {
                "clause_id": "§7",
                "clause_type": "governing_law",
                "severity": "high",
                "issue": "NY law is bad",
                "evidence": "",
                "redline": "Delaware",
            }
        )
        return json.dumps(out)

    r = review(responder=hallucinator)
    assert any("UNSUPPORTED governing_law" in fb for h in r["history"] for fb in h["feedback"])
    assert "governing_law" not in findings(r)


def test_guardrail_blocks_prohibited_redline():
    def unsafe(msgs):
        if "REVIEW" not in str(msgs[0].content):
            return mock_responder(msgs)
        out = json.loads(mock_responder(msgs))
        for f in out["findings"]:
            if f["clause_type"] == "indemnification":
                f["redline"] = (
                    "Each party covers third-party claims; Customer shall waive all "
                    "rights to recover."
                )
        return json.dumps(out)

    r = review(responder=unsafe)
    assert any("waive all" in b for b in r["report"]["guardrail_blocks"])
    assert "waive" not in findings(r)["indemnification"]["redline"]


def test_eval_harness_precision_recall_and_gate():
    res = run_eval(build_graph(llm=MockChatModel(responder=mock_responder)))
    assert (res.tp, res.fp, res.fn) == (12, 1, 1)
    assert res.precision == pytest.approx(12 / 13) and res.recall == pytest.approx(12 / 13)
    assert gate(res, 0.8, 0.8)[0] is True
    ok, reasons = gate(res, 0.95, 0.95)
    assert not ok and len(reasons) == 2
    rows = {r["id"]: r for r in res.rows}
    assert rows["EV3-evergreen"]["fn"] == ["auto_renewal"]  # known playbook gap
    assert rows["EV2-balanced"]["fp"] == ["limitation_of_liability"]  # known false positive
