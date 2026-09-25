"""Logistics exception agent: stream consumer, TMS grounding, notices, claims, A2A."""

import pytest
from fastapi.testclient import TestClient

from exception_agent import capacity
from exception_agent.eval_suite import run, slip_event
from exception_agent.events import (
    CheckpointStore,
    Consumer,
    EventHub,
    MilestoneEvent,
    MilestoneTrigger,
    slipped,
)
from exception_agent.graph import build_graph
from exception_agent.systems import seed_systems
from shared.a2a import A2AClient, A2AError


def test_partitioning_keeps_shipment_order():
    hub = EventHub(partitions=4)
    parts = {hub.send({"n": i}, "SH-1001")[0] for i in range(5)}
    assert len(parts) == 1


def test_slip_detection():
    assert slipped(MilestoneEvent.model_validate(slip_event("SH-1001")))
    on_time = slip_event("SH-1001", actual_at="2026-09-25T10:30", status="on_time")
    assert not slipped(MilestoneEvent.model_validate(on_time))
    missed = slip_event("SH-1001", actual_at=None, status="missed")
    assert slipped(MilestoneEvent.model_validate(missed))


def test_crash_and_replay_triggers_once():
    hub, store, calls = EventHub(), CheckpointStore(), []
    hub.send(slip_event("SH-1001"), "SH-1001")
    hub.send(slip_event("SH-1003", tenant="contoso"), "SH-1003")

    def run_(req):
        calls.append(req["shipment_id"])
        return {}

    MilestoneTrigger(Consumer(hub, "g", store), run_).poll(crash_after=1)
    # simulate a crash *after* running but before checkpoint by rewinding offsets
    store.offsets.clear()
    MilestoneTrigger(Consumer(hub, "g", store), run_).poll()
    assert sorted(calls) == ["SH-1001", "SH-1003"]


def test_malformed_event_dead_lettered_and_checkpointed():
    hub, store = EventHub(partitions=1), CheckpointStore()
    hub.send({"shipment_id": "x"}, "x")
    trig = MilestoneTrigger(Consumer(hub, "g", store), lambda r: r)
    assert trig.poll() == [] and len(trig.dead_letter) == 1
    assert store.offsets[("g", 0)] == 0


def test_track_refuses_to_interpolate_on_scan_gap():
    r, _ = run({"kind": "track", "shipment_id": "SH-1002", "eager_model": True})
    assert r["outcome"] == "scan_gap" and "Shreveport" in r["answer"]
    assert r["gap_h"] > 6


def test_track_guard_blocks_interpolating_model():
    r, _ = run({"kind": "track", "shipment_id": "SH-1001", "eager_model": True})
    assert "Pittsburgh" not in r["answer"] and "[EV-1001-3]" in r["answer"]


def test_notice_only_on_high_confidence():
    _, s = run({"kind": "slip", "shipment_id": "SH-1001"})
    assert len(s.notices) == 1 and s.notices[0]["status"] == "draft"
    _, s = run(
        {
            "kind": "slip",
            "shipment_id": "SH-1004",
            "event": {"source": "driver_app", "confidence": 0.7},
        }
    )
    assert s.notices == []


def test_notice_is_idempotent_per_milestone():
    s = seed_systems()
    g = build_graph(s)
    from exception_agent.eval_suite import request

    for i in range(2):
        g.invoke(
            {"request": request({"kind": "slip", "shipment_id": "SH-1001"})},
            {"configurable": {"thread_id": f"n{i}"}},
        )
    assert len(s.notices) == 1


@pytest.mark.parametrize("docs", ["smudged", "handwritten"])
def test_low_ocr_confidence_queues_claim(docs):
    r, s = run({"kind": "claim", "shipment_id": "SH-1003", "tenant": "contoso", "documents": docs})
    assert r["outcome"] == "claim_queued" and not s.claims and len(s.review_queue) == 1


def test_claim_window_uses_edition_on_ship_date():
    r, _ = run({"kind": "claim", "shipment_id": "SH-1003", "tenant": "contoso"})
    assert r["claim"]["rule"] == "CLM-RIDGELINE-2026"
    r, _ = run({"kind": "claim", "shipment_id": "SH-1005", "tenant": "contoso", "documents": "old"})
    assert "CLM-RIDGELINE-2025" in r["answer"] and r["outcome"] == "claim_queued"


def test_capacity_agent_card_and_whatif():
    c = capacity.client()
    assert c.card().name == "capacity-agent"
    t = c.send(
        "network_whatif",
        {"shipment_id": "SH-1001", "lane": "CHI-NYC", "delay_hours": 5.5},
        tenant="northwind",
    )
    out = t.artifacts[0].data()
    assert out["options"] and "SMA(4)" in out["method"]


def test_capacity_agent_rejects_unregistered_caller_and_bad_schema():
    with pytest.raises(A2AError):
        capacity.client(caller="rogue-agent").send(
            "network_whatif",
            {"shipment_id": "SH-1001", "lane": "CHI-NYC", "delay_hours": 1},
            tenant="northwind",
        )
    with pytest.raises(A2AError):
        capacity.client().send(
            "network_whatif",
            {"shipment_id": "bad", "lane": "x", "delay_hours": -1},
            tenant="northwind",
        )


def test_capacity_refusal_escalates_but_notice_continues():
    rogue = A2AClient("capacity-agent", TestClient(capacity.app()), caller="rogue-agent")
    s = seed_systems()
    g = build_graph(s, capacity_client=rogue)
    from exception_agent.eval_suite import request

    r = g.invoke(
        {"request": request({"kind": "slip", "shipment_id": "SH-1001"})},
        {"configurable": {"thread_id": "rogue"}},
    )
    assert ["whatif", "escalate"] in [[e["node"], e["exit"]] for e in r["exits"]]
    assert len(s.notices) == 1
