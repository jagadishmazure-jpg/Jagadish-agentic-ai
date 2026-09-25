"""CLI demo: `python run.py` - prior auth with PHI redaction, plan-year RAG and sign-off.

1) Gold PPO lumbar MRI (2026 rules) -> draft -> clinician signs -> submitted
2) same note, 2025 date of service -> 6-week rule not met (plan-year temporal)
3) Silver HMO -> referral rule only its plan can see (ACL)
4) member channel: status, then a medical-advice question (refused)
5) kill switch on coverage language
"""

from __future__ import annotations

import argparse
import itertools
import logging
import sys
from pathlib import Path

from langgraph.types import Command

from prior_auth.eval_suite import request
from prior_auth.graph import build_graph
from prior_auth.systems import seed_systems

_ids = itertools.count(1)


def provider(g, *args, **kw) -> dict:
    cfg = {"configurable": {"thread_id": f"demo-{next(_ids)}"}}
    r = g.invoke({"request": request(*args, **kw)}, cfg)
    if "__interrupt__" in r:
        pk = r["__interrupt__"][0].value["packet"]
        print(
            f"  ⏸ clinician console: criteria={pk['criteria']['status']} "
            f"unmet={pk['criteria']['unmet']} flags={pk['flags']}"
        )
        print(f"    narrative: {pk['narrative']}")
        r = g.invoke(Command(resume={"clinician": "dr-osei", "decision": "approve"}), cfg)
    print("  ->", r["answer"])
    return r


def member(g, question: str) -> None:
    cfg = {"configurable": {"thread_id": f"demo-{next(_ids)}"}}
    req = {"channel": "member", "member_id": "M-1001", "question": question}
    print(f"  member: {question}\n  bot:    {g.invoke({'request': req}, cfg)['answer']}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mermaid", type=Path, help="write the compiled graph as mermaid text")
    args = ap.parse_args(argv)
    s = seed_systems()
    g = build_graph(s)
    if args.mermaid:
        args.mermaid.write_text(g.get_graph(xray=1).draw_mermaid())
        print(f"wrote {args.mermaid}")
        return
    log = logging.getLogger("prior_auth")
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("  log (PHI filter): %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False
    print("=== 1) Gold PPO, 2026 plan year ===")
    r = provider(g, "M-1001", "pt5")
    print(f"  redacted note sent to the model: {r['note_redacted'].splitlines()[0]}")
    log.removeHandler(handler)
    print("\n=== 2) same note, 2025 date of service ===")
    provider(g, "M-1001", "pt5", dos="2025-09-10")
    print("\n=== 3) Silver HMO (referral rule visible to this plan only) ===")
    provider(g, "M-2002", "pt5")
    print("\n=== 4) member channel ===")
    member(g, "What's the status of my MRI approval?")
    member(g, "Should I take ibuprofen for my back while I wait?")
    print("\n=== 5) kill switch: coverage language off ===")
    s.switches.kill("coverage_language")
    provider(g, "M-1001", "pt5")


if __name__ == "__main__":
    main()
