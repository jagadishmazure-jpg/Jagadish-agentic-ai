"""CLI demo: `python run.py [--mermaid graph.mmd]`."""

from __future__ import annotations

import argparse
from pathlib import Path

from ticket_triage.graph import build_graph

TICKETS = [
    {
        "id": "T-1",
        "subject": "Charged twice",
        "body": "I was charged twice on my invoice this month, please refund. "
        "Card 4111 1111 1111 1111, email jane.doe@example.com",
    },
    {
        "id": "T-2",
        "subject": "API down",
        "body": "Production down: every API endpoint returns 500 error and timeout for all "
        "customers since 09:00. Call me at (555) 123-4567.",
    },
    {
        "id": "T-3",
        "subject": "Locked out",
        "body": "I'm locked out after the password reset and the 2FA code never arrives.",
    },
    {"id": "T-4", "subject": "Help", "body": "The dashboard is broken."},
    {"id": "T-5", "subject": "hello", "body": "Hi there, quick question for you."},
]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mermaid", type=Path)
    args = parser.parse_args(argv)
    graph = build_graph()
    if args.mermaid:
        args.mermaid.write_text(graph.get_graph().draw_mermaid())
        print(f"wrote {args.mermaid}")
        return
    for t in TICKETS:
        r = graph.invoke({"ticket": t})
        res = r["result"]
        c = res["classification"] or {}
        print(f"\n{t['id']} {t['subject']!r}")
        print(f"   LLM saw: {r['redacted'][:110]!r}")
        print(f"   path: {' -> '.join(r['trace'])}")
        print(
            f"   {c.get('intent')}/{c.get('urgency')}/{c.get('product')} "
            f"conf={c.get('confidence')} -> {res['route']} {res['queue'] or ''} "
            f"sla={res['sla_hours']} page={res['page_on_call']} redactions={res['redactions']}"
        )
        print(f"   reply: {res['customer_reply']}")


if __name__ == "__main__":
    main()
