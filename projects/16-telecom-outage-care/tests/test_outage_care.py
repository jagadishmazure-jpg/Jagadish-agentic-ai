"""Topology blast radius, OSS freshness, citations, upsell block, dispatch pack, NOC mode."""

from outage_care import topology
from outage_care.eval_suite import run
from outage_care.sor import gateways
from outage_care.systems import seed_systems


def test_blast_radius_is_redundancy_aware():
    assert topology.blast_radius(["AGG-2"]) == {"nodes": ["OLT-21"], "accounts": ["A-200"]}
    both = topology.blast_radius(["AGG-1"], already_down=["AGG-2"])
    assert both["nodes"] == ["CELL-7", "OLT-11", "OLT-12"]
    assert both["accounts"] == ["A-100", "A-300", "A-400"]
    assert topology.blast_radius(["CORE-1"])["accounts"] == ["A-100", "A-200", "A-300", "A-400"]


def test_confirmed_outage_blocks_offers_and_dispatch():
    r, s = run({"account": "A-200", "message": "internet down"})
    assert r["outage"]["incident"] == "INC-1" and r["offers_blocked"] == "confirmed outage"
    assert not s.dispatches and "upgrade" not in r["answer"].lower()


def test_stale_feed_is_disclosed_not_asserted():
    r, _ = run({"account": "A-200", "message": "internet down", "oss_lag_min": 40})
    assert r["outage"]["state"] == "unknown" and "40 minutes old" in r["answer"]
    assert "confirmed outage" not in r["answer"]


def test_dispatch_context_pack():
    _, s = run({"account": "A-400", "message": "internet not working"})
    pack = s.dispatches[0]
    assert pack["service_path"] == ["OLT-12", "AGG-1", "CORE-1"]
    assert pack["line_test"]["ont"] == "offline" and pack["status_age_min"] == 5
    assert pack["nearby_incidents"] == ["INC-1"]


def test_dispatch_idempotent_per_day():
    from outage_care.graph import build_graph

    s = seed_systems()
    g = build_graph(s)
    for t in ("a", "b"):
        g.invoke(
            {"request": {"channel": "app", "account": "A-400", "message": "no internet"}},
            {"configurable": {"thread_id": t}},
        )
    assert len(s.dispatches) == 1


def test_bill_citations_follow_bill_period_edition():
    r, _ = run({"account": "A-400", "message": "explain my bill"})
    assert r["bill_lines"][0]["cite"] == "TAR-FIBER-500-2025"
    r, _ = run({"account": "A-100", "message": "explain my bill"})
    assert [x["cite"] for x in r["bill_lines"]] == [
        "TAR-FIBER-500-2026",
        "TAR-PRORATION-1",
        "TAR-EQUIP-1",
    ]


def test_noc_identity_is_read_only():
    gw = gateways(seed_systems())
    assert gw["noc"].allow == {"oss.get_active_incidents"}
    r, s = run({"channel": "noc", "message": "Reboot AGG-2 and dispatch a crew"})
    assert "only summarise" in r["answer"] and not s.dispatches


def test_noc_what_if():
    r, _ = run({"channel": "noc", "message": "What if AGG-1 fails?"})
    w = r["outage"]["facts"]["what_if"]
    assert w["given_current_incidents"] == ["AGG-2"] and "CELL-7" in w["nodes"]
