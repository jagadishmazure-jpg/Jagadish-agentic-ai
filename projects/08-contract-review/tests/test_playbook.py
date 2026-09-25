from contract_review.contracts import DEMO
from contract_review.playbook import LEGAL_OPS, SENIOR_COUNSEL, builder, playbook_context
from contract_review.rules import keyword_type, segment


def _clauses():
    return [{**c, "type": keyword_type(c["heading"], c["text"])} for c in segment(DEMO)]


def test_playbook_entry_retrieved_per_clause_type():
    ctx = playbook_context(builder(), _clauses())
    assert ctx["limitation_of_liability"]["id"] == "PB-LIMITATION-OF-LIABILITY"
    assert "12 months" in ctx["limitation_of_liability"]["text"]


def test_senior_fallbacks_are_acl_trimmed_for_the_review_agent():
    kb = builder()
    q = "liability fallback cap 6 months of fees"
    agent_hits, *_ = kb.retrieve(q, LEGAL_OPS)
    assert not any(h.chunk_id.endswith("FALLBACK") for h in agent_hits)
    senior_hits, *_ = kb.retrieve(q, SENIOR_COUNSEL)
    assert any(h.chunk_id.endswith("FALLBACK") for h in senior_hits)
