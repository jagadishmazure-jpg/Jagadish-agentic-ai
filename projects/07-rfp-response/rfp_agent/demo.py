"""CLI demo: `python run.py [--mermaid graph.mmd]`."""

from __future__ import annotations

import argparse
from pathlib import Path

from rfp_agent.graph import build_graph
from rfp_agent.knowledge import RFP


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mermaid", type=Path)
    args = parser.parse_args(argv)
    graph = build_graph()
    if args.mermaid:
        args.mermaid.write_text(graph.get_graph(xray=1).draw_mermaid())
        print(f"wrote {args.mermaid}")
        return
    r = graph.invoke({"rfp_text": RFP})
    print("planned sections:", [(s["name"], len(s["questions"])) for s in r["sections"]])
    print("\nper-question critic loop:")
    for a in r["final_answers"]:
        print(
            f"  {a['id']:<3} {a['status']:<9} drafts={a['attempts']} cites={a['citations']}"
            + (f"  last issues={a['issues']}" if a["issues"] else "")
        )
    d = r["document"]
    print(f"\ncompliance: removed={d['banned_claims_removed']}")
    print(f"            export-control={d['export_control_hits']}")
    print("\n" + d["markdown"])


if __name__ == "__main__":
    main()
