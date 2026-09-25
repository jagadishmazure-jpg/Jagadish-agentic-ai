"""CLI demo: `python run.py` - technician copilot.

1) 2022 X5 coolant leak -> current TSB-23-107 (32 Nm), harness rev B diagram, ATP with part
   supersession, warranty claim after administrator approval
2) same car, repair dated 2022-10-01 -> TSB-21-044 was current then (25 Nm)
3) wrong-version model (remembers 25 Nm / old part) -> safety check replaces the guidance
4) 2021 build infotainment -> TSB build-date filter excludes it
5) the agent tries to approve its own claim -> refused
"""

from __future__ import annotations

import argparse
import itertools
from pathlib import Path

from langgraph.types import Command

from shared.llm import MockChatModel
from tech_copilot.graph import build_graph, stale_responder
from tech_copilot.systems import seed_systems

_ids = itertools.count(1)


def job(g, vin: str, concern: str, dtcs=(), repair_date="2026-09-25", approver="wa-rivera"):
    cfg = {"configurable": {"thread_id": f"demo-{next(_ids)}"}}
    req = {
        "ro": f"RO-{next(_ids)}",
        "vin": vin,
        "concern": concern,
        "dtcs": list(dtcs),
        "repair_date": repair_date,
        "dealer": "D-12",
    }
    r = g.invoke({"request": req}, cfg)
    print(f"\n[{vin} {repair_date}] {concern}")
    if "__interrupt__" in r:
        print(f"  HITL warranty claim pending: {r['__interrupt__'][0].value['coverage']}")
        r = g.invoke(Command(resume={"admin": approver, "decision": "approve"}), cfg)
    print("  tsbs:", r.get("tsbs"), "dropped:", r.get("dropped"), "images:", r.get("images"))
    print("  guidance:", r["procedure"].replace("\n", "\n            "))
    print("  parts:", r.get("parts"))
    print("  outcome:", r["outcome"], "| exits:", [(e["node"], e["exit"]) for e in r["exits"]])
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
    job(g, "VIN-X5-22-0001", "coolant leak at pump", ["P0128"])
    print("  claims:", s.claims)
    job(g, "VIN-X5-22-0001", "coolant leak at pump", ["P0128"], repair_date="2022-10-01")
    print("\n=== wrong-version model ===")
    job(
        build_graph(seed_systems(), llm=MockChatModel(responder=stale_responder)),
        "VIN-X5-22-0001",
        "coolant leak at pump",
        ["P0128"],
    )
    job(g, "VIN-X5-21-0002", "infotainment head unit reboot loop")
    print("\n=== agent tries to approve ===")
    job(
        build_graph(seed_systems()),
        "VIN-C3-24-0004",
        "charge port door will not open",
        ["B1A42"],
        approver="mi-tech-copilot",
    )


if __name__ == "__main__":
    main()
