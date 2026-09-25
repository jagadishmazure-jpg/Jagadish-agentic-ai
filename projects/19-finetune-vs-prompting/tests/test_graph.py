"""Serving graph: champion routing, confidence gate, PII boundary, idempotent LOS writes."""

from finetune_lab.baseline import mock_responder
from finetune_lab.graph import build_graph
from finetune_lab.labels import SYSTEM_PROMPT_BASELINE
from finetune_lab.registry import ModelRegistry
from shared.llm import MockChatModel

PAYSTUB = (
    "Earnings Statement\nPay period 05/01 - 05/15\nGross pay $3,950.00\nNet pay $2,801.33\n"
    "Borrower: Rowan Whitford SSN 402-19-5521"
)


def _doc(text, doc_id="T-1"):
    return {"doc": {"doc_id": doc_id, "loan_id": "LN-1", "text": text}}


def test_champion_files_a_confident_document():
    g = build_graph()
    r = g.invoke(_doc(PAYSTUB))
    assert r["result"]["route"] == "filed" and r["result"]["doc_type"] == "pay_stub"
    assert r["result"]["model_version"] == g.registry.champion.version
    assert g.los.filed["T-1"]["doc_type"] == "pay_stub"


def test_low_confidence_goes_to_a_processor_not_a_guess():
    g = build_graph()
    r = g.invoke(_doc("Dear team, please see attached. Thanks!"))
    assert r["result"]["route"] == "human_review" and "confidence" in r["result"]["reason"]
    assert "T-1" in g.los.review and not g.los.filed


def test_pii_is_scrubbed_before_the_model_and_never_filed():
    seen = []

    def spy(messages):
        seen.append(str(messages[-1].content))
        return mock_responder(messages)

    reg = ModelRegistry()
    base = reg.register_prompt(SYSTEM_PROMPT_BASELINE, "mock")
    reg.record_metrics(base.version, "val", {"accuracy": 1.0, "macro_f1": 1.0})
    reg.promote(base.version)
    g = build_graph(registry=reg, llm=MockChatModel(responder=spy))
    r = g.invoke(_doc(PAYSTUB))
    assert seen and all("5521" not in s and "Whitford" not in s for s in seen)
    assert r["redactions"] == {"SSN": 1, "NAME": 1}
    assert "Whitford" not in str(g.los.filed)


def test_replay_is_idempotent_in_the_los():
    g = build_graph()
    g.invoke(_doc(PAYSTUB))
    g.invoke(_doc(PAYSTUB))
    assert len(g.los.filed) == 1
    assert len([c for c in g.gateway.log if c.tool == "los.file_document"]) == 2
