"""CLI demo: `python run.py [--mermaid graph.mmd] [--reject]`."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import Command

from incident_agent.graph import build_graph
from incident_agent.systems import seed_systems

ALERTS = [
    {"id": "INC-4411", "service": "checkout-api", "alert": "5xx error rate > 5% for 5 min"},
    {"id": "INC-4412", "service": "search-api", "alert": "p99 latency > 2s for 10 min"},
]


def print_trace(messages) -> None:
    for m in messages:
        if isinstance(m, AIMessage) and m.tool_calls:
            for tc in m.tool_calls:
                print(f"   🤖 -> {tc['name']}({tc['args']})")
        elif isinstance(m, ToolMessage):
            print(f"   🔧 {m.name}: {str(m.content)[:110]}")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mermaid", type=Path)
    parser.add_argument("--reject", action="store_true", help="reject the proposed rollback")
    args = parser.parse_args(argv)
    systems = seed_systems()
    graph = build_graph(systems)
    if args.mermaid:
        args.mermaid.write_text(graph.get_graph(xray=1).draw_mermaid())
        print(f"wrote {args.mermaid}")
        return
    for alert in ALERTS:
        cfg = {"configurable": {"thread_id": alert["id"]}}
        print(f"\n=== {alert['id']} {alert['service']}: {alert['alert']} ===")
        r = graph.invoke({"alert": alert}, cfg)
        if "__interrupt__" in r:
            req = r["__interrupt__"][0].value
            print(
                f"   ⏸  APPROVAL NEEDED: rollback {req['service']} -> {req['to_version']} "
                f"({req['reason']})"
            )
            decision = (
                {"approved": False, "note": "want to hotfix pool size instead"}
                if args.reject
                else {"approved": True, "approver": "oncall-sam"}
            )
            print(f"   human: {decision}")
            r = graph.invoke(Command(resume=decision), cfg)
        print_trace(r["messages"])
        rep = r["report"]
        print(
            json.dumps(
                {
                    k: rep[k]
                    for k in (
                        "status",
                        "root_cause",
                        "confidence",
                        "evidence",
                        "mitigation",
                        "tool_cost",
                    )
                },
                indent=2,
            )
        )
    print("\nrollbacks executed:", systems.deploys.rollbacks)


if __name__ == "__main__":
    main()
