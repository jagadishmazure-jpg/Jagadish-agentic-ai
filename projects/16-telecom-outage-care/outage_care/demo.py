"""CLI demo: `python run.py` - outage-aware care and the summarise-only NOC assistant.

1) customer on the failed aggregation path -> confirmed outage + ETA, no upsell
2) dual-homed mobile customer in the same area -> not affected
3) no outage but ONT offline -> field dispatch with a context pack
4) bill explained with tariff citations (edition as-of the bill period)
5) stale OSS feed -> disclosed, no truck roll
6) NOC: incident summary, what-if blast radius, action request refused
"""

from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

from outage_care.graph import build_graph
from outage_care.systems import seed_systems

_ids = itertools.count(1)


def ask(g, account: str, message: str, channel: str = "app") -> dict:
    r = g.invoke(
        {"request": {"channel": channel, "account": account, "message": message}},
        {"configurable": {"thread_id": f"demo-{next(_ids)}"}},
    )
    print(f"  [{channel} {account}] {message}\n    -> {r['answer']}")
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
    print("=== customer care (OSS feed 5 min old) ===")
    ask(g, "A-200", "My internet is down")
    ask(g, "A-300", "No signal on my phone")
    ask(g, "A-400", "Internet not working since this morning")
    print("    dispatch context pack:", json.dumps(s.dispatches[0], default=str)[:220], "...")
    ask(g, "A-100", "Why is my bill higher this month?")
    print("\n=== stale OSS feed (50 min) ===")
    g2 = build_graph(seed_systems(oss_lag_min=50))
    ask(g2, "A-400", "internet down")
    print("\n=== NOC console (read-only identity) ===")
    ask(g, "", "Summarize active incidents", "noc")
    ask(g, "", "What happens if AGG-1 dies?", "noc")
    ask(g, "", "Restart AGG-2 now", "noc")


if __name__ == "__main__":
    main()
