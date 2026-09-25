"""CLI demo: `python run.py [--mermaid graph.mmd] [question ...]`."""

from __future__ import annotations

import argparse
from pathlib import Path

from policy_qa.graph import build_graph

QUESTIONS = [
    "How many PTO days can I carry over?",
    "Can I get reimbursed for my wifi when I wfh?",  # weak first retrieval -> retry
    "What is the meal allowance when traveling?",  # source chunk contains an injection
    "What is the stock option vesting schedule?",  # not in corpus -> insufficient evidence
]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mermaid", type=Path)
    parser.add_argument("questions", nargs="*")
    args = parser.parse_args(argv)
    graph = build_graph()
    if args.mermaid:
        args.mermaid.write_text(graph.get_graph().draw_mermaid())
        print(f"wrote {args.mermaid}")
        return
    for q in args.questions or QUESTIONS:
        r = graph.invoke({"question": q})
        f = r["final"]
        print(f"\nQ: {q}")
        print(f"   path: {' -> '.join(r['trace'])}")
        print(f"   queries: {f['queries']}")
        print(f"   [{f['status']}] {f['answer']}")
        if f["citations"]:
            print(
                "   sources: "
                + "; ".join(f"{c['id']} ({c['doc']} / {c['section']})" for c in f["citations"])
            )
        if f["flagged_injections"]:
            print(f"   sanitized injection: {f['flagged_injections']}")
        if f["reason"]:
            print(f"   reason: {f['reason']}")


if __name__ == "__main__":
    main()
