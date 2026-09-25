"""FNOL graph: OCR confidence gate, edition/jurisdiction RAG, fraud as a tool, HITL money."""

from fnol import ocr, rules
from fnol.eval_suite import leaky_responder
from fnol.graph import CUSTOMER_FORBIDDEN
from fnol.knowledge import EDITION_DATES, builder, principal
from shared.llm import MockChatModel

SENIOR = {"approver": "adj-senior-ortiz", "decision": "approve"}


def test_ocr_confidence_pairs():
    out = ocr.analyze("Policy Number: HO-1\n[hw] Estimated Amount: 50\nDate of Loss: 2026-0~1-02")
    f = out["fields"]
    assert f["policy_number"] == {"value": "HO-1", "confidence": 0.98}
    assert f["estimate"]["confidence"] == 0.78
    assert f["loss_date"] == {"value": "2026-01-02", "confidence": 0.45}
    assert set(ocr.low_confidence(f)) == {"estimate", "loss_date", "description"}


def test_low_confidence_goes_to_queue_without_claim(run, systems):
    r = run("DOC-BLURRY")
    assert r["outcome"] == "queued" and "policy_number" in r["queue_reason"]
    assert systems.queue and not systems.claims
    assert "Q-0001" in r["customer_message"]


def test_interrupt_carries_proposal_and_waits(run, systems):
    r = run("DOC-WATER-TX")
    payload = r["__interrupt__"][0].value
    assert payload["type"] == "reserve_payment_approval"
    assert payload["proposal"]["reserve"] == 17400.0
    assert payload["proposal"]["citations"] == ["HO3-2023-WATER::1"]
    assert not systems.reserves and not systems.payments  # nothing before the adjuster


def test_edition_decides_seepage(run):
    assert run("DOC-SEEP-TX23", SENIOR)["coverage"]["status"] == "excluded"
    assert run("DOC-SEEP-TX19", SENIOR)["coverage"]["status"] == "covered"


def test_retrieval_is_scoped_by_edition_and_state():
    kb = builder()
    b = kb.build("water mold coverage", principal("TX"), as_of=EDITION_DATES["2019"], k=10)
    docs = {c.split("::")[0] for c in b.chunk_ids}
    assert "TX-AMEND-2019-MOLD" in docs and "HO3-2019-WATER" in docs
    assert not docs & {
        "TX-AMEND-2023-MOLD",
        "CA-AMEND-2023-MOLD",
        "HO3-2023-WATER",
        "SIU-GUIDE-INT",
    }
    assert b.dropped_temporal > 0 and b.dropped_acl > 0


def test_jurisdiction_sublimits(run):
    assert run("DOC-MOLD-TX", SENIOR)["proposal"]["reserve"] == 15000.0
    assert run("DOC-MOLD-CA", SENIOR)["proposal"]["reserve"] == 16500.0


def test_fraud_score_comes_from_the_tool_and_never_reaches_claimant(run, systems):
    r = run("DOC-FIRE-NEW", SENIOR)
    assert r["fraud"]["model_version"] == "fraud-gbm-2026.07" and r["fraud"]["band"] == "high"
    assert r["proposal"]["siu_referral"] and r["proposal"]["payment"] == 0.0
    assert systems.reserves and not systems.payments
    assert "SIU" in r["adjuster_note"]
    assert not CUSTOMER_FORBIDDEN.search(r["customer_message"])


def test_leaky_model_is_guarded(run):
    r = run("DOC-FIRE-NEW", SENIOR, llm=MockChatModel(responder=leaky_responder))
    assert not CUSTOMER_FORBIDDEN.search(r["customer_message"])
    assert any(e["node"] == "finalize" and "claimant guard" in e["reason"] for e in r["exits"])


def test_authority_limits_and_non_adjusters(run, systems):
    r = run("DOC-OVER-LIMIT", {"approver": "adj-kim", "decision": "approve"})
    assert r["approval"]["decision"] == "referred" and not systems.payments
    r = run("DOC-WATER-TX", {"approver": "mi-fnol-agent", "decision": "approve"})
    assert r["approval"]["decision"] == "rejected" and not systems.payments


def test_timeout_never_pays(run, systems):
    r = run("DOC-WATER-TX", {"timeout": True})
    assert r["outcome"] == "open" and not systems.payments and not systems.reserves


def test_payment_idempotent_on_replay(systems):
    from langgraph.types import Command

    from fnol.graph import build_graph

    g = build_graph(systems)
    for t in ("a", "b"):  # two threads, same packet -> same idempotency keys
        cfg = {"configurable": {"thread_id": t}}
        g.invoke({"request": {"document_id": "DOC-WATER-TX"}}, cfg)
        g.invoke(Command(resume=SENIOR), cfg)
    assert len(systems.payments) == 1 and len(systems.claims) == 1


def test_payable_rules():
    p = {"dwelling_limit": 40000, "deductible": 1000}
    cov = rules.coverage("wind", "2023", "TX", 0, 0)
    assert rules.payable(55000, 0, cov, p)["payable"] == 39000
    assert rules.coverage("flood", "2019", "TX", 0, 0)["status"] == "excluded"
