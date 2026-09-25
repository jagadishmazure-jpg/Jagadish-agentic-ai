"""CLI demo: `python run.py [--mermaid graph.mmd] [--fail news]`."""

from __future__ import annotations

import argparse
from pathlib import Path

from meeting_prep.graph import build_graph
from meeting_prep.sources import seed_sources

MEETING = {
    "date": "2026-09-29 10:00 ET",
    "attendees": ["Dana Ruiz (VP Ops)", "Raj Patel"],
    "goal": "Expand analytics to EU and secure the 3-year renewal",
}


def run(fail: list[str], latency: float) -> dict:
    sources = seed_sources(
        failures={s: ConnectionError("503 from upstream") for s in fail}, latency_s=latency
    )
    graph = build_graph(sources)
    return graph.invoke({"account_id": "ACME", "account_name": "Acme Corp", "meeting": MEETING})


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mermaid", type=Path)
    parser.add_argument("--fail", action="append", default=[], help="source to break")
    args = parser.parse_args(argv)
    if args.mermaid:
        args.mermaid.write_text(build_graph(seed_sources()).get_graph().draw_mermaid())
        print(f"wrote {args.mermaid}")
        return
    scenarios = [
        ("all sources healthy (each source sleeps 0.2s)", [], 0.2),
        ("news API down -> partial brief", ["news"], 0.0),
    ]
    if args.fail:
        scenarios = [(f"failing: {args.fail}", args.fail, 0.0)]
    for title, fail, latency in scenarios:
        r = run(fail, latency)
        print(f"\n===== {title} =====")
        print("branch timings:", r["timings"])
        print(r["brief"]["markdown"])


if __name__ == "__main__":
    main()
