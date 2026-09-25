from datetime import date

from incident_agent.knowledge import SRE_AGENT, builder, lookup
from shared.context import Principal


def test_runbook_lookup_is_hybrid_and_current():
    cid, text = lookup(builder(), "connection pool exhausted")
    assert cid == "RB-DB-07" and "roll back to the previous version" in text


def test_superseded_edition_applies_to_old_incidents():
    cid, text = lookup(builder(), "connection pool exhausted", as_of=date(2025, 6, 1))
    assert cid == "RB-DB-07@2025" and "do not roll back" in text


def test_dba_runbook_is_acl_trimmed_for_the_sre_agent():
    kb = builder()
    assert lookup(kb, "primary database failover") is None
    hits, *_ = kb.retrieve("primary database failover", Principal.of("dba-1", "dba"))
    assert hits[0].chunk_id == "RB-DB-09"
    _, d_acl_sre, *_ = kb.retrieve("primary database failover", SRE_AGENT)
    assert d_acl_sre >= 1
