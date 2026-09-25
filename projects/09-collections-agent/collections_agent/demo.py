"""CLI demo: `python run.py [--mermaid graph.mmd] [--reject]`."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from langgraph.types import Command

from collections_agent.graph import build_graph
from collections_agent.systems import seed_systems


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mermaid", type=Path)
    parser.add_argument("--reject", action="store_true", help="reviewer rejects the plan")
    args = parser.parse_args(argv)
    systems = seed_systems()
    graph = build_graph(systems)
    if args.mermaid:
        args.mermaid.write_text(graph.get_graph().draw_mermaid())
        print(f"wrote {args.mermaid}")
        return
    print("least-privilege tool registry:")
    for ident in ("collections-reader", "plan-proposer", "plan-writer", "outreach-sender"):
        print(f"  {ident:20} -> {systems.registry.tools_for(ident)}")
    for acct in ("A-1001", "A-1002", "A-1003", "A-1004", "A-1005"):
        cfg = {"configurable": {"thread_id": acct}}
        r = graph.invoke({"account_id": acct}, cfg)
        print(f"\n== {acct}: decision={r['decision']} reasons={r['reasons']}")
        if "__interrupt__" in r:
            req = r["__interrupt__"][0].value
            print("  REVIEW REQUEST (masked):", json.dumps(req["account"]), "| plan:", req["plan"])
            print("  draft message:\n    " + req["draft_message"].replace("\n", "\n    "))
            decision = "reject" if args.reject else "approve"
            r = graph.invoke(Command(resume={"decision": decision, "reviewer": "j.meduri"}), cfg)
        print(
            f"  outcome: {r['outcome']}",
            r.get("plan_record", {}).get("plan_id", ""),
            r.get("message_record", {}).get("message_id", ""),
            r.get("next_allowed", ""),
        )
    ok, _ = systems.audit.verify()
    print(f"\naudit log: {len(systems.audit.entries)} entries, hash chain valid={ok}")
    for e in systems.audit.entries[:6]:
        print(
            f"  #{e['seq']:02d} {e['hash'][:10]} {e['actor']:20} {e['action']:26} "
            f"{json.dumps(e['details'])[:90]}"
        )
    print("  ...")


if __name__ == "__main__":
    main()
