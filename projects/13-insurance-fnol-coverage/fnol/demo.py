"""CLI demo: `python run.py` - scanned FNOL packets through coverage to adjuster approval.

1) clean water-loss packet -> cited coverage -> adjuster approves -> reserve + payment
2) same seepage loss on a 2019 vs 2023 form edition -> different coverage
3) new policy with prior claims -> fraud model band high -> SIU hold; claimant message neutral
4) blurry policy number -> manual indexing queue (nothing guessed)
"""

from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

from langgraph.types import Command

from fnol import ocr
from fnol.graph import build_graph
from fnol.systems import seed_systems

SENIOR = {"approver": "adj-senior-ortiz", "decision": "approve"}
_ids = itertools.count(1)


def run(g, doc: str, review: dict | None = None) -> dict:
    cfg = {"configurable": {"thread_id": f"demo-{next(_ids)}"}}
    r = g.invoke({"request": {"document_id": doc}}, cfg)
    if "__interrupt__" in r:
        p = r["__interrupt__"][0].value
        print(f"  ⏸ adjuster workbench: {p['adjuster_note']}")
        review = review or {
            **SENIOR,
            "decision": "approve" if p["proposal"]["recommendation"] == "pay" else "deny",
        }
        r = g.invoke(Command(resume=review), cfg)
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
    print("=== 1) clean packet (OCR fields) ===")
    fields = ocr.analyze(s.packets["DOC-WATER-TX"])["fields"]
    print(json.dumps(dict(list(fields.items())[:4]), indent=1))
    r = run(g, "DOC-WATER-TX")
    print(f"  citations={r['citations']}  outcome={r['outcome']}")
    print("  claimant:", r["customer_message"])
    print("\n=== 2) form edition decides seepage ===")
    for doc in ("DOC-SEEP-TX23", "DOC-SEEP-TX19"):
        r = run(g, doc)
        print(
            f"  {doc}: edition {r['policy']['edition']} -> {r['coverage']['status']} "
            f"({r['coverage']['reason']})"
        )
    print("\n=== 3) fraud model band high ===")
    r = run(g, "DOC-FIRE-NEW")
    print(f"  fraud tool: {r['fraud']}")
    print("  claimant:", r["customer_message"])
    print("\n=== 4) blurry policy number ===")
    r = run(g, "DOC-BLURRY")
    print(f"  {r['queue_reason']} -> {r['customer_message']}")
    print(f"\nwrites: reserves={s.reserves}\n        payments={s.payments}")


if __name__ == "__main__":
    main()
