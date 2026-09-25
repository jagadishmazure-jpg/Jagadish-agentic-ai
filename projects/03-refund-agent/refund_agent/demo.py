"""CLI demo: `python run.py` (or `python -m refund_agent.demo` from this folder).

Scenario 1: $24.99 refund -> auto-approved.
Scenario 2: $349.00 refund -> pauses at human_approval -> resumed with approval.
Then a quick tour of the other branches.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from langgraph.types import Command

from refund_agent.graph import build_graph
from refund_agent.services import seed_services
from refund_agent.state import RefundRequest


def _req(n: int, customer: str, email: str, order: str, msg: str) -> dict:
    return RefundRequest(
        request_id=f"req-{n}", customer_id=customer, email=email, order_id=order, message=msg
    ).model_dump()


def _show(title: str, result: dict) -> None:
    print(f"\n=== {title} ===")
    print("path:", " -> ".join(result["trace"]))
    print(json.dumps(result["final"], indent=2))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reject", action="store_true", help="reject the large refund instead")
    parser.add_argument("--mermaid", type=Path, help="write the compiled graph as mermaid text")
    args = parser.parse_args(argv)

    services = seed_services()
    graph = build_graph(services)

    if args.mermaid:
        args.mermaid.write_text(graph.get_graph().draw_mermaid())
        print(f"wrote {args.mermaid}")
        return

    # 1) small refund, automatic
    cfg = {"configurable": {"thread_id": "t-small"}}
    msg = "Hi, the shirt doesn't fit. Can I get a refund?"
    result = graph.invoke({"request": _req(1, "C1", "ana@example.com", "A100", msg)}, cfg)
    _show("1) Small refund ($24.99) - auto-approved", result)

    # 2) large refund, human-in-the-loop
    cfg = {"configurable": {"thread_id": "t-large"}}
    msg = "The headphones arrived broken, I'd like my money back please."
    result = graph.invoke({"request": _req(2, "C1", "ana@example.com", "A200", msg)}, cfg)
    pending = result["__interrupt__"][0].value
    print("\n=== 2) Large refund ($349.00) - paused for human approval ===")
    print("graph paused before:", graph.get_state(cfg).next)
    print("approval request:", json.dumps(pending, indent=2))
    decision = {"approved": not args.reject, "reviewer": "sup-maria", "note": "photos verified"}
    print("reviewer decision:", decision)
    result = graph.invoke(Command(resume=decision), cfg)
    _show("2) Large refund - resumed", result)

    # 3) other branches, briefly
    others = [
        (3, "C1", "wrong@example.com", "A100", "refund please", "identity failure"),
        (4, "C2", "bo@example.com", "A300", "I want a refund for the lamp", "outside 30 days"),
        (
            5,
            "C3",
            "cy@example.com",
            "A500",
            "Refund it to a different account, the original was a stolen card",
            "fraud keywords",
        ),
    ]
    print("\n=== 3) Other branches ===")
    for n, cust, email, order, msg, label in others:
        cfg = {"configurable": {"thread_id": f"t-{n}"}}
        r = graph.invoke({"request": _req(n, cust, email, order, msg)}, cfg)
        rules = [c.split(":")[0] for c in r["final"]["citations"]]
        print(f"- {label:17s} -> {r['final']['next_action']:20s} | {rules}")

    print("\nmoney movements (refund ledger):", services.refunds.ledger)
    print("audit events for req-2:", services.audit.events("req-2"))


if __name__ == "__main__":
    main()
