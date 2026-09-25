"""CLI demo: `python run.py [--mermaid graph.mmd]`."""

from __future__ import annotations

import argparse
from pathlib import Path

from contract_review.contracts import DEMO
from contract_review.graph import build_graph


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mermaid", type=Path)
    args = parser.parse_args(argv)
    graph = build_graph()
    if args.mermaid:
        args.mermaid.write_text(graph.get_graph().draw_mermaid())
        print(f"wrote {args.mermaid}")
        return
    r = graph.invoke({"text": DEMO})
    print("clauses:", [(c["id"], c["type"]) for c in r["clauses"]])
    print("\nevaluator-optimizer iterations:")
    for h in r["history"]:
        print(
            f"  iter {h['iteration']}: {h['findings']} findings, {len(h['feedback'])} "
            f"feedback items"
        )
        for fb in h["feedback"]:
            print(f"      - {fb}")
    rep = r["report"]
    print(f"\n{rep['title']}")
    print(
        f"risk score {rep['risk_score']} ({rep['risk_tier']}) -> {rep['route']}; "
        f"evaluation passed: {rep['evaluation_passed']}"
    )
    for f in rep["findings"]:
        print(
            f"  [{f['severity'].upper():8}] {f['clause_id'] or '—':3} {f['clause_type']}: "
            f"{f['issue']}"
        )
        if f["redline"]:
            print(f"             redline: {f['redline']}")
    print(f"\n{rep['disclaimer']}")


if __name__ == "__main__":
    main()
