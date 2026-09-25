"""CLI demo: `python run.py` - the late-shipment refund journey through the BFF.

1) $48.99 refund, auto-approved and confirmed by the provider (SSE stream shown)
2) $249 refund -> specialist approval via the console endpoint
3) payment provider down -> queued with an honest reference, then the worker redelivers
4) fraud pre-route and a vague message
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fastapi.testclient import TestClient

from care_e2e.bff import create_app
from care_e2e.graph import build_graph
from care_e2e.sor import build_gateways
from care_e2e.systems import seed_systems
from care_e2e.worker import drain
from shared import faults

H = {"Authorization": "Bearer tok-ana", "X-Tenant-Id": "acme-retail"}
SAM = {"Authorization": "Bearer tok-sam", "X-Tenant-Id": "acme-retail"}


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
    c = TestClient(create_app(s, g))
    msg = {"message": "My shipment O-1001 is late, can I get a refund?"}

    print("=== 1) SSE stream: small refund ===")
    with c.stream("POST", "/v1/channels/web/messages/stream", json=msg, headers=H) as r:
        for event in "".join(r.iter_text()).split("\n\n"):
            if event.startswith("event: node"):
                print("  node:", json.loads(event.split("data: ")[1])["node"])
            elif event.startswith("event: done"):
                print(json.dumps(json.loads(event.split("data: ")[1]), indent=2))

    print("\n=== 2) Large refund -> specialist ===")
    big = {"message": "My shipment O-1005 is late, can I get a refund?"}
    r = c.post("/v1/channels/web/messages", json=big, headers=H).json()
    print(json.dumps(r, indent=2))
    r = c.post(f"/v1/approvals/{r['thread_id']}", json={"decision": "approve"}, headers=SAM)
    print("after approval:", r.json()["status"], "-", r.json()["reply"])

    print("\n=== 3) Payment provider down -> honest queue ===")
    faults.inject("sor:payments")
    r = c.post(
        "/v1/channels/app/messages",
        json={"message": "Order O-1002 is late, I want a refund."},
        headers=H,
    ).json()
    faults.clear("sor:payments")
    print(r["status"], "-", r["reply"])
    print("worker redelivered:", drain(s, build_gateways(s)["writer"]), "command(s)")

    print("\n=== 4) Fraud pre-route + vague message ===")
    cy = {"Authorization": "Bearer tok-cy", "X-Tenant-Id": "acme-retail"}
    fraud = {"message": "My shipment O-3001 is late, refund?"}
    print(c.post("/v1/channels/web/messages", json=fraud, headers=cy).json()["reply"])
    print(
        c.post("/v1/channels/web/messages", json={"message": "refund please"}, headers=H).json()[
            "reply"
        ]
    )


if __name__ == "__main__":
    main()
