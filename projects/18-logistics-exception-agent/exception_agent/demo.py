"""CLI demo: `python run.py` - event-driven logistics exceptions.

1) milestone stream: 4 events (duplicate slip, on-time, malformed) -> one graph run, one
   notice draft, one dead-letter; a crash + restart replays without re-triggering
2) tracking: fresh scans -> cited answer; scans stopped -> no interpolation
3) inferred slip event -> no customer notice, exception desk
4) carrier claim from OCR'd docs: clean -> draft with rule edition; smudged -> queue
"""

from __future__ import annotations

import argparse
import itertools
from pathlib import Path

from exception_agent.eval_suite import CLAIM_DOCS, request, slip_event
from exception_agent.events import CheckpointStore, Consumer, EventHub, MilestoneTrigger
from exception_agent.graph import build_graph
from exception_agent.systems import seed_systems

_ids = itertools.count(1)


def ask(g, inp: dict) -> dict:
    r = g.invoke({"request": request(inp)}, {"configurable": {"thread_id": f"d-{next(_ids)}"}})
    print(f"  [{inp['kind']} {inp['shipment_id']}] -> {r['outcome']}\n    {r['answer']}")
    return r


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mermaid", type=Path, help="write the compiled graph as mermaid text")
    args = ap.parse_args(argv)
    s = seed_systems()
    g = build_graph(s)
    if args.mermaid:
        args.mermaid.write_text(g.get_graph().draw_mermaid())
        print(f"wrote {args.mermaid}")
        return
    print("=== milestone stream (Event Hubs stand-in, 2 partitions) ===")
    hub, store = EventHub(), CheckpointStore()
    for body in (
        slip_event("SH-1001"),
        slip_event("SH-1001"),
        slip_event("SH-1004", actual_at="2026-09-25T09:40", status="on_time"),
        {"shipment_id": "SH-9", "garbage": True},
    ):
        hub.send(body, partition_key=body["shipment_id"])

    def run(req):
        r = g.invoke({"request": req}, {"configurable": {"thread_id": f"ev-{next(_ids)}"}})
        print(f"  triggered {req['shipment_id']} -> {r['outcome']}\n    {r['answer']}")
        return r

    trig = MilestoneTrigger(Consumer(hub, "exceptions", store), run)
    trig.poll()
    print("  -- checkpoint lost (crash before checkpoint write): replaying the partition --")
    store.offsets.clear()
    trig = MilestoneTrigger(Consumer(hub, "exceptions", store), run)
    print(f"  replay triggered {len(trig.poll())} new runs (dedupe on shipment+milestone)")
    print(f"  notices: {len(s.notices)}  dead-letter: {trig.dead_letter}")
    print("\n=== tracking (TMS events only) ===")
    ask(g, {"kind": "track", "shipment_id": "SH-1001"})
    ask(g, {"kind": "track", "shipment_id": "SH-1002"})
    print("\n=== inferred slip ===")
    ask(
        g,
        {
            "kind": "slip",
            "shipment_id": "SH-1004",
            "event": {"source": "inferred", "confidence": 0.6},
        },
    )
    print("\n=== carrier claims from OCR'd documents ===")
    ask(g, {"kind": "claim", "shipment_id": "SH-1003", "tenant": "contoso"})
    ask(g, {"kind": "claim", "shipment_id": "SH-1003", "tenant": "contoso", "documents": "smudged"})
    print("\n  OCR sample:", CLAIM_DOCS["smudged"].splitlines()[5])


if __name__ == "__main__":
    main()
