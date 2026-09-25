"""CLI demo: `python run.py [--mermaid graph.mmd]`."""

from __future__ import annotations

import argparse
from pathlib import Path

from invoice_match.erp import seed_erp
from invoice_match.graph import build_graph
from invoice_match.invoices import INVOICES

SCENARIOS = [
    ("clean", "clean 3-way match"),
    ("variance", "price variance + partial receipt + line not on PO"),
    ("no_po", "PO not found (typed ERP error)"),
    ("clean", "same invoice re-submitted"),
    ("messy", "messy layout: extraction retry, then cumulative qty check vs INV-1001"),
]


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mermaid", type=Path)
    args = parser.parse_args(argv)
    erp = seed_erp()
    erp.unavailable_for = 1  # first ERP call hits a transient 503 -> RetryPolicy
    graph = build_graph(erp)
    if args.mermaid:
        args.mermaid.write_text(graph.get_graph().draw_mermaid())
        print(f"wrote {args.mermaid}")
        return
    for key, label in SCENARIOS:
        r = graph.invoke({"raw_text": INVOICES[key]})
        res = r["result"]
        print(f"\n=== {res['invoice_number']}: {label} ===")
        print(f"   path: {' -> '.join(r['trace'])}")
        print(
            f"   status: {res['status']} -> {res['route_to']}"
            + (f" (payment doc {res['payment_doc']})" if res["payment_doc"] else "")
        )
        if res["exception_note"]:
            print("   " + res["exception_note"].replace("\n", "\n   "))
    print(f"\nERP calls: {erp.calls} (includes 1 transient 503 retried automatically)")


if __name__ == "__main__":
    main()
