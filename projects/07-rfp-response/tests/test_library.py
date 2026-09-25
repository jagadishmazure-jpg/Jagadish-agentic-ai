from datetime import date

from rfp_agent.library import builder, search
from shared.context import Principal


def test_pricing_entry_is_acl_trimmed_for_presales():
    q = "What discount do you offer on multi-year analytics platform deals?"
    assert "KB-PRC-001" not in [e["id"] for e in search(builder(), q)]
    desk = Principal.of("desk-1", "deal-desk")
    assert search(builder(), q, principal=desk)[0]["id"] == "KB-PRC-001"


def test_sla_edition_follows_submission_date():
    q = "What uptime SLA do you offer?"
    assert search(builder(), q)[0]["id"] == "KB-OPS-001"
    assert search(builder(), q, as_of=date(2025, 6, 30))[0]["id"] == "KB-OPS-901"
