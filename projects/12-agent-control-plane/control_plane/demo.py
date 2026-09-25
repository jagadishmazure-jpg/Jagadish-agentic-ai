"""CLI demo: `python run.py` - governed A2A mesh.

1) journey agent asks CRM, SAP-like and Databricks-like demand agents in parallel (one trace)
2) shortfall -> draft PO over A2A (policy allows it for tenant northwind only)
3) governance: unregistered caller, marketing agent denied a write, schema rejection
4) kill switch on sap-agent -> journey degrades honestly; promotion gate refuses a weak agent
"""

from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

from fastapi.testclient import TestClient

from control_plane.agents import build_network
from control_plane.api import create_app
from control_plane.journey import build_graph
from control_plane.registry import AgentRecord
from shared.a2a import A2AClient, A2AError

ADMIN = {"X-Admin-Token": "tok-platform-admin"}
_ids = itertools.count(1)


def ask(g, text: str, tenant: str = "northwind") -> dict:
    cfg = {"configurable": {"thread_id": f"demo-{next(_ids)}"}}
    return g.invoke({"request": {"tenant": tenant, "text": text}}, cfg)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mermaid", type=Path, help="write the compiled graph as mermaid text")
    args = ap.parse_args(argv)
    net = build_network()
    g = build_graph(net)
    if args.mermaid:
        args.mermaid.write_text(g.get_graph().draw_mermaid())
        print(f"wrote {args.mermaid}")
        return
    api = TestClient(create_app(net))

    print("=== agent cards (/.well-known/agent.json) ===")
    for name in ("crm-agent", "sap-agent", "demand-agent"):
        card = api.get(f"/agents/{name}/.well-known/agent.json").json()
        print(f"  {card['name']} v{card['version']}: {[s['id'] for s in card['skills']]}")

    print("\n=== 1) promise within ATP ===")
    r = ask(g, "Can we promise 300 units of SKU-200 to ACME-B2B within 4 weeks?")
    print(" ", r["answer"])
    traces = {a["traceparent"].split("-")[1] for a in net.cp.audit}
    print(f"  {len(net.cp.audit)} A2A calls, {len(traces)} trace id(s): {sorted(traces)}")

    print("\n=== 2) shortfall -> PO draft over A2A ===")
    print(" ", ask(g, "Can we promise 500 units of SKU-200 to ACME-B2B within 4 weeks?")["answer"])
    r = ask(g, "Can we promise 900 units of SKU-200 to INITECH-B2B within 4 weeks?", "contoso")
    print("  contoso:", r["answer"], "|", r["exits"][-1]["reason"])

    print("\n=== 3) governance ===")
    for caller, skill, data in (
        ("rogue-agent", "get_stock", {"sku": "SKU-200"}),
        (
            "marketing-agent",
            "create_po_draft",
            {"sku": "SKU-200", "qty": 50, "reason": "promo", "idempotency_key": "k1"},
        ),
        ("journey-agent", "get_stock", {"sku": "200"}),
    ):
        try:
            A2AClient("sap-agent", TestClient(net.apps["sap-agent"]), caller).send(
                skill, data, tenant="northwind"
            )
        except A2AError as exc:
            print(f"  {caller}.{skill}: rejected ({exc.code}) {exc.reason}")

    print("\n=== 4) kill switch + promotion gate ===")
    api.post("/registry/agents/sap-agent/kill", json={"reason": "bad release"}, headers=ADMIN)
    r = ask(g, "Can we promise 300 units of SKU-200 to ACME-B2B within 4 weeks?")
    print(" ", r["answer"])
    weak = AgentRecord(
        name="pricing-agent",
        version="0.1.0",
        purpose="sets contract prices",
        owner="pricing team",
        skills={"set_price": "irreversible_write"},
        tenants=["northwind"],
        eval_scores={"task_success": 0.91, "policy_violation_rate": 0.0},
    )
    api.post("/registry/agents", json=weak.model_dump(), headers=ADMIN)
    r = api.post("/registry/agents/pricing-agent/promote", headers=ADMIN)
    print(f"  promote pricing-agent -> {r.status_code}: {r.json()['detail']}")
    print("\nlast audit entries:")
    print(json.dumps(net.cp.audit[-3:], indent=1))


if __name__ == "__main__":
    main()
