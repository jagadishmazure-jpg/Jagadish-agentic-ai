"""Per-agent MCP identities: each gateway can reach exactly its job's tools."""

import pytest

from shared.tools import ToolDeniedError
from supply_chain.services import seed_services
from supply_chain.sor import SCOPES, build_gateways


@pytest.fixture
def gws():
    return build_gateways(seed_services())


def test_only_the_orchestrator_can_release_or_cancel(gws):
    for agent in ("demand", "inventory", "supplier"):
        with pytest.raises(ToolDeniedError):
            gws[agent].call("erp", "submit_purchase_order", draft_id="D", idempotency_key="k")
    assert SCOPES["orchestrator"][1] == {"erp.submit_purchase_order", "erp.cancel_po_draft"}


def test_cancelled_draft_cannot_be_released_and_released_cannot_be_cancelled():
    s = seed_services()
    gws = build_gateways(s)
    d1 = s.erp.create_draft(supplier="Acme", sku="SKU-100", qty=1, unit_price=1.0, total=1.0)
    d2 = s.erp.create_draft(supplier="Acme", sku="SKU-100", qty=2, unit_price=1.0, total=2.0)
    orch = gws["orchestrator"]
    orch.call(
        "erp", "submit_purchase_order", draft_id=d1["draft_id"], idempotency_key="a", dry_run=False
    )
    with pytest.raises(ValueError):
        orch.call(
            "erp",
            "cancel_po_draft",
            draft_id=d1["draft_id"],
            reason="x",
            idempotency_key="c1",
            dry_run=False,
        )
    orch.call(
        "erp",
        "cancel_po_draft",
        draft_id=d2["draft_id"],
        reason="x",
        idempotency_key="c2",
        dry_run=False,
    )
    with pytest.raises(ValueError):
        orch.call(
            "erp",
            "submit_purchase_order",
            draft_id=d2["draft_id"],
            idempotency_key="b",
            dry_run=False,
        )
    assert [p["draft_id"] for p in s.erp.submitted] == [d1["draft_id"]]


def test_semantic_model_serves_certified_measure_only(gws):
    vals = gws["demand"].call("analytics", "get_measure", measure="weekly_units", entity="SKU-100")
    assert vals["values"][-1] == 135
    with pytest.raises(KeyError):
        gws["demand"].call("analytics", "get_measure", measure="raw_sql", entity="SKU-100")
