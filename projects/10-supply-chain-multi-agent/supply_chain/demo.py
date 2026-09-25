"""CLI demo: `python run.py [--mermaid graph.mmd] [--sku SKU-100]`.

Runs the four mock scenarios (reorder + approval, no reorder, fallback supplier,
reviewer loop) plus an approval rejection, printing the agent-hop trace.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from langgraph.types import Command

from supply_chain.graph import build_graph
from supply_chain.services import seed_services

SCENARIOS = [
    ("SKU-100", True, "reorder needed -> HITL approve"),
    ("SKU-200", True, "enough stock -> finish without supplier agent"),
    ("SKU-300", True, "preferred supplier quote unavailable -> fallback"),
    ("SKU-400", True, "reviewer loop: preferred supplier not cheapest acceptable"),
    ("SKU-100", False, "approval rejected (fresh ERP)"),
]


def print_trace(hops: list[dict]) -> None:
    print(f"  {'step':>4}  {'agent':<16} {'ms':>7}  detail")
    for h in hops:
        if h["agent"] == "supervisor":
            detail = f"route {h['decision']} - {h['reason']}"
        elif "tools" in h:
            detail = f"tools {h['tools']}"
            if h.get("unavailable"):
                detail += f" | quote unavailable: {h['unavailable']} -> fallback"
        elif h["agent"] == "reviewer":
            detail = "PASS" if h["passed"] else f"FAIL {h['issues']}"
        elif h["agent"] == "human_approval":
            detail = f"approved={h['approved']} by {h['approver']}"
        else:
            detail = f"PO {h.get('po_number')} replayed={h.get('replayed')}"
        print(f"  {h['step']:>4}  {h['agent']:<16} {h.get('duration_ms', 0):>7}  {detail}")


def run_scenario(graph, sku: str, approve: bool, label: str, thread: str) -> dict:
    print(f"\n=== {sku}: {label} ===")
    cfg = {"configurable": {"thread_id": thread}}
    result = graph.invoke({"sku": sku, "horizon_weeks": 4}, cfg)
    if "__interrupt__" in result:
        rec = result["__interrupt__"][0].value["recommendation"]
        print(
            f"  PAUSED before submit: {rec['qty']} x {sku} from {rec['supplier']} "
            f"@ {rec['unit_price']:.2f} = ${rec['total_cost']:,.2f} ({rec['draft_id']})"
        )
        decision = {"approved": approve, "approver": "buyer-lee", "note": "demo"}
        print(f"  human decision: {decision}")
        result = graph.invoke(Command(resume=decision), cfg)
    print_trace(result["hops"])
    final = result["final"]
    print(f"  OUTCOME: {final['outcome']} - {final['summary']}")
    return final


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mermaid", type=Path, help="write the compiled graph as mermaid text")
    parser.add_argument("--sku", help="run a single SKU (auto-approves)")
    args = parser.parse_args(argv)

    services = seed_services()
    graph = build_graph(services)
    if args.mermaid:
        args.mermaid.write_text(graph.get_graph().draw_mermaid())
        print(f"wrote {args.mermaid}")
        return
    if args.sku:
        run_scenario(graph, args.sku, True, "single run", f"cli-{args.sku}")
        return

    finals = []
    for i, (sku, approve, label) in enumerate(SCENARIOS):
        if not approve:  # separate ERP so the earlier SKU-100 PO doesn't affect it
            services = seed_services()
            graph = build_graph(services)
        finals.append(run_scenario(graph, sku, approve, label, f"demo-{i}"))

    print("\n=== Final recommendation (SKU-100) ===")
    print(json.dumps(finals[0]["recommendation"], indent=2))


if __name__ == "__main__":
    main()
