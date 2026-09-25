"""Prior auth: PHI redaction (context + logs), ACL/plan-year RAG, eligibility unknown,
draft-only + clinician signature, member-channel advice guardrail, kill switch."""

import logging
from datetime import date

import pytest

from prior_auth.eval_suite import PHI, advice_responder, request, run
from prior_auth.knowledge import builder, principal
from prior_auth.phi import redact
from prior_auth.systems import note, seed_systems
from shared.llm import MockChatModel


def test_redact_removes_phi():
    text = redact(note("M-1001", "5 weeks of physical therapy"), ["Jordan Blake"])
    assert not any(
        p in text
        for p in ("Jordan", "Blake", "MRN-558812", "1979-04-12", "123-45-6789", "512-555-0142")
    )
    assert "5 weeks of physical therapy" in text


def test_logs_are_redacted_even_when_raw_values_are_logged(caplog):
    caplog.set_level(logging.INFO, logger="prior_auth")
    run({"provider": {"member": "M-1001", "body": "pt5"}})
    joined = "\n".join(r.getMessage() for r in caplog.records)
    assert "pa request" in joined and "[NAME]" in joined
    assert not any(p in joined for p in PHI)
    assert "M-1001" not in joined  # member ids masked in logs


def test_context_pack_has_no_phi():
    r, _, _ = run({"provider": {"member": "M-1001", "body": "pt5"}})
    assert not any(p in r["note_redacted"] for p in PHI)
    assert not any(p in (r["narrative"] or "") for p in PHI)


def test_acl_and_plan_year():
    kb = builder()
    gold = kb.build(
        "imaging referral criteria 72148", principal("gold-ppo"), as_of=date(2026, 5, 1), k=10
    )
    ids = {c.split("::")[0] for c in gold.chunk_ids}
    assert "MP-LSPINE-MRI-2026" in ids and "MP-SILVER-REFERRAL-2026" not in ids
    assert "MP-LSPINE-MRI-2025" not in ids and "UM-MD-GUIDE-INT" not in ids
    silver = kb.build(
        "imaging referral criteria 72148", principal("silver-hmo"), as_of=date(2026, 5, 1), k=10
    )
    assert "MP-SILVER-REFERRAL-2026" in {c.split("::")[0] for c in silver.chunk_ids}


def test_plan_year_changes_the_answer():
    r26, _, _ = run({"provider": {"member": "M-1001", "body": "pt5"}})
    r25, _, _ = run({"provider": {"member": "M-1001", "body": "pt5", "dos": "2025-09-10"}})
    assert r26["criteria"]["status"] == "criteria_met"
    assert r25["criteria"]["status"] == "criteria_not_met"
    assert r25["citations"][0].startswith("MP-LSPINE-MRI-2025")


def test_draft_only_until_clinician_signs():
    from prior_auth.graph import build_graph

    s = seed_systems()
    g = build_graph(s)
    cfg = {"configurable": {"thread_id": "pa-1"}}
    r = g.invoke({"request": request("M-1001", "pt5")}, cfg)
    assert r["__interrupt__"][0].value["type"] == "clinician_signoff"
    assert [d["status"] for d in s.drafts.values()] == ["draft"] and not s.submissions


def test_portal_rejects_unsigned_submission():
    s = seed_systems()
    s.save_draft({"member_id": "M-1001", "cpt": "72148"})
    with pytest.raises(PermissionError):
        s.submit("PA-D0001", "mi-pa-agent")


def test_eligibility_failure_is_unknown_not_eligible():
    r, s, _ = run({"provider": {"member": "M-1001", "body": "pt5"}, "fault": "sor:eligibility"})
    assert r["eligibility"]["status"] == "unknown"
    assert "eligibility unknown - verify before service" in s.drafts["PA-D0001"]["flags"]


def test_member_channel_refuses_advice_and_blocks_advice_model():
    q = {"channel": "member", "member_id": "M-1001", "question": "What can I take for the pain?"}
    r, _, _ = run({"member_request": q})
    assert "can't give medical advice" in r["answer"]
    q2 = {**q, "question": "Any news on my request?"}
    r, _, _ = run({"member_request": q2, "advice_model": True})
    assert "mg" not in r["answer"] and "nurse line" in r["answer"]


def test_kill_switch_disables_coverage_language_only():
    r, _s, _ = run({"provider": {"member": "M-1001", "body": "pt5"}, "kill": ["coverage_language"]})
    assert r["narrative"] is None and r["criteria"]["status"] == "criteria_met"
    assert r["submission"]  # the rest of the workflow keeps running


def test_bad_citation_replaced_by_template():
    def fabricating(msgs):
        return "Approved per [MP-MADE-UP-2026]." if "COVERAGE" in str(msgs[0].content) else ""

    from langgraph.types import Command

    from prior_auth.graph import build_graph

    g = build_graph(seed_systems(), llm=MockChatModel(responder=fabricating))
    cfg = {"configurable": {"thread_id": "fab"}}
    r = g.invoke({"request": request("M-1001", "pt5")}, cfg)
    r = g.invoke(Command(resume={"clinician": "np-lin", "decision": "approve"}), cfg)
    assert "MP-MADE-UP" not in r["narrative"] and "[MP-LSPINE-MRI-2026]" in r["narrative"]


def test_advice_responder_would_leak_without_guardrail():
    out = advice_responder(
        [
            type("M", (), {"content": "TASK: MEMBER"})(),
            type("M", (), {"content": '{"requests": [], "question": ""}'})(),
        ]
    )
    assert "400 mg" in out
