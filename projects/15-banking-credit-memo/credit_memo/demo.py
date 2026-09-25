"""CLI demo: `python run.py` - credit memo with governed measures and dual control.

1) Northwind: ownership graph as of the application date, semantic-layer dry-run plans,
   cited memo, maker + checker approvals, limit booked
2) same approver twice -> dual control refused
3) cheap fallback model tries to skip KYC for a trust-owned borrower -> KYC still runs, stops
4) over-levered borrower -> decline recommendation, no approval path
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from langgraph.types import Command

from credit_memo.eval_suite import CHECKER, MAKER, request
from credit_memo.graph import build_graph, fast_track_responder
from credit_memo.systems import seed_systems
from shared import faults
from shared.llm import MockChatModel


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
    print("=== 1) Northwind Fabrication, $5m revolver ===")
    cfg = {"configurable": {"thread_id": "demo-1"}}
    r = g.invoke({"request": request()}, cfg)
    print("  UBOs as of application date:", r["ownership"]["ubos"])
    print("  semantic plan (dry run):", json.dumps(r["measure_plans"][2]))
    print("  memo:\n    " + r["memo"].replace("\n", "\n    "))
    r = g.invoke(Command(resume=MAKER), cfg)
    r = g.invoke(Command(resume=CHECKER), cfg)
    print(f"  -> {r['status']}: {r['booking']} approvals={r['approvals']}")

    print("\n=== 2) same approver twice ===")
    cfg = {"configurable": {"thread_id": "demo-2"}}
    g.invoke({"request": request()}, cfg)
    g.invoke(Command(resume=CHECKER), cfg)
    r = g.invoke(Command(resume=CHECKER), cfg)
    print(f"  -> {r['status']}: {r['exits'][-1]['reason']}")

    print("\n=== 3) fallback model tries to fast-track (skip KYC) ===")
    g2 = build_graph(s, fallback_llm=MockChatModel(responder=fast_track_responder))
    with faults.fault("model:primary"):
        r = g2.invoke({"request": request("B-200")}, {"configurable": {"thread_id": "demo-3"}})
    for e in r["exits"]:
        print(f"  {e['node']} -> {e['exit']}: {e['reason']}")
    print(f"  -> {r['status']}")

    print("\n=== 4) over-levered borrower ===")
    r = g.invoke({"request": request("B-400")}, {"configurable": {"thread_id": "demo-4"}})
    print(f"  -> {r['status']}: {r['memo'].splitlines()[-1]}")


if __name__ == "__main__":
    main()
