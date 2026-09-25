"""Technician copilot: supersession, applicability, wrong-version safety, warranty HITL."""

import pytest

from shared.llm import MockChatModel
from tech_copilot.eval_suite import run
from tech_copilot.graph import build_graph, specs, stale_responder
from tech_copilot.knowledge import applies, current_only
from tech_copilot.systems import VEHICLES, seed_systems

COOL = {"vin": "VIN-X5-22-0001", "concern": "coolant leak at pump", "dtcs": ["P0128"]}


def test_current_tsb_wins_over_unretired_predecessor():
    r, _ = run(COOL)
    assert r["tsbs"] == ["TSB-23-107"]
    assert "TSB-21-044" in r["dropped"]["superseded"]
    assert "32 Nm" in r["procedure"] and "25 Nm" not in r["procedure"]


def test_as_of_repair_date_before_supersession():
    r, _ = run({**COOL, "repair_date": "2022-10-01"})
    assert r["tsbs"] == ["TSB-21-044"] and "25 Nm" in r["procedure"]


def test_wrong_version_safety():
    """A model that recalls the superseded spec must never reach the technician."""
    s = seed_systems()
    g = build_graph(s, llm=MockChatModel(responder=stale_responder))
    cfg = {"configurable": {"thread_id": "wv"}}
    req = {
        "ro": "RO-9",
        "vin": COOL["vin"],
        "concern": COOL["concern"],
        "dtcs": ["P0128"],
        "repair_date": "2026-09-25",
        "dealer": "D-12",
    }
    r = g.invoke({"request": req}, cfg)
    assert {"25 Nm", "11-4455-A"}.isdisjoint(specs(r["procedure"]))
    assert "TSB-21-044" not in r["procedure"]
    assert any(e["node"] == "procedure" and "safety" in e["reason"] for e in r["exits"])


def test_build_date_applicability():
    assert not applies("TSB-22-061", {"vin": "x", **VEHICLES["VIN-X5-21-0002"]})
    assert applies("TSB-22-061", {"vin": "x", **VEHICLES["VIN-X5-22-0001"]})


def test_current_only_needs_valid_successor():
    assert current_only(["TSB-21-044"], set()) == (["TSB-21-044"], [])
    assert current_only(["TSB-21-044"], {"TSB-23-107"}) == ([], ["TSB-21-044"])


def test_diagram_harness_revision_and_relevance():
    r, _ = run(COOL)
    assert r["images"] == ["IMG-WD-X5-COOL-B"]
    r, _ = run({"vin": "VIN-X5-22-0001", "concern": "infotainment head unit reboot loop"})
    assert r["images"] == []


def test_part_supersession_in_atp():
    r, _ = run({**COOL, "repair_date": "2022-10-01"})
    assert r["parts"][0]["part_number"] == "11-4455-C"
    assert r["parts"][0]["replaces"] == "11-4455-A"


def test_warranty_always_interrupts_when_covered():
    g = build_graph(seed_systems())
    cfg = {"configurable": {"thread_id": "w"}}
    req = {
        "ro": "RO-1",
        "vin": COOL["vin"],
        "concern": COOL["concern"],
        "dtcs": ["P0128"],
        "repair_date": "2026-09-25",
        "dealer": "D-12",
    }
    r = g.invoke({"request": req}, cfg)
    assert r["__interrupt__"][0].value["type"] == "warranty_claim"


@pytest.mark.parametrize("who", ["mi-tech-copilot", "tech-jones", ""])
def test_non_admin_cannot_approve(who):
    r, s = run({**COOL, "approval": {"admin": who, "decision": "approve"}})
    assert not s.claims and r["outcome"] == "warranty_not_approved"


def test_claim_is_idempotent_and_attributed():
    r, s = run(COOL)
    assert len(s.claims) == 1 and s.claims[0]["approved_by"] == "wa-rivera"
    assert r["claim"]["claim_ref"].startswith("WC-")


def test_customer_pay_has_no_claim_or_hitl():
    r, s = run({"vin": "VIN-X5-23-0003", **{k: COOL[k] for k in ("concern", "dtcs")}})
    assert r["outcome"] == "customer_pay" and not s.claims
    assert "warranty_approval" not in r["trace"]
