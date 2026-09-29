"""CLI demo.

python run.py                                  # L-2105 through all eight patterns
python run.py --pattern swarm --loan L-2111    # one pattern with the per-agent trace
python run.py --pattern magentic --fault analyst_down
python run.py --hitl                           # referral pauses for a credit officer
python run.py --compare [--write | --check]    # comparison tables (README source)
python run.py --mermaid graph.mmd              # arena graph + graphs/<pattern>.mmd
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from langgraph.types import Command

from orchestration_lab import compare
from orchestration_lab.graph import PATTERNS, build_graph
from orchestration_lab.harness import FaultPlan, Harness
from orchestration_lab.sor import LoanSystems

FAULTS = {
    "analyst_down": FaultPlan(down="analyst"),
    "looping_reviewer": FaultPlan(loop=True),
    "bad_handoff": FaultPlan(bad_handoff=True),
}


def print_trace(trace: list[dict]) -> None:
    print(
        f"  {'agent':<24} {'start s':>8} {'sim ms':>7} {'llm':>4} {'tokens':>6} {'tools':>5}  note"
    )
    for t in trace:
        note = t["note"] if t["ok"] else f"FAILED {t['error']}"
        print(
            f"  {t['agent']:<24} {t['start_ms'] / 1000:>8.2f} {t['ms']:>7.0f} {t['llm_calls']:>4} "
            f"{t['tokens']:>6} {t['tool_calls']:>5}  {note[:70]}"
        )


def run_one(pattern: str, loan: str, fault: FaultPlan | None, trace: bool) -> dict:
    g = build_graph(systems=LoanSystems(), faults=fault, hitl=False)
    r = g.invoke({"loan_id": loan, "pattern": pattern}, {"configurable": {"thread_id": pattern}})
    f = r["final"]
    m = f["metrics"]
    print(
        f"{pattern:<13} {f['decision']:<24} {f['stop_reason']:<32} turns={m['turns']:>2} "
        f"llm={m['llm_calls']:>2} tokens={m['tokens']:>5} sim={m['sim_latency_ms'] / 1000:>5.1f}s"
    )
    if trace:
        print_trace(f["trace"])
        if f["memo"]:
            print(f"  memo: {f['memo']}")
    return f


def hitl_demo() -> None:
    g = build_graph(systems=LoanSystems(), hitl=True)
    cfg = {"configurable": {"thread_id": "hitl-demo"}}
    r = g.invoke({"loan_id": "L-2103", "pattern": "supervisor"}, cfg)
    ask = r["__interrupt__"][0].value
    print(f"PAUSED for credit officer: {ask['loan_id']} reason={ask['reason']}")
    print(f"  memo: {ask['memo']}")
    answer = {"decision": "approve_with_conditions", "approver": "credit-officer-demo"}
    print(f"  officer answers: {answer}")
    r = g.invoke(Command(resume=answer), cfg)
    f = r["final"]
    print(f"FINAL: {f['decision']} decided_by={f.get('decided_by')} filed={f['filed']}")


def write_mermaid(path: Path) -> None:
    path.write_text(build_graph().get_graph().draw_mermaid())
    out = path.parent / "graphs"
    out.mkdir(exist_ok=True)
    for name, mod in PATTERNS.items():
        g = mod.build(Harness(name))
        (out / f"{name}.mmd").write_text(g.get_graph(xray=1).draw_mermaid())
    print(f"wrote {path} and {out}/<pattern>.mmd")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--pattern", choices=sorted(PATTERNS))
    ap.add_argument("--loan", default="L-2105")
    ap.add_argument("--fault", choices=sorted(FAULTS))
    ap.add_argument("--hitl", action="store_true")
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--mermaid", type=Path)
    args = ap.parse_args(argv)
    if args.mermaid:
        write_mermaid(args.mermaid)
        return
    if args.compare:
        sys.exit(compare.main(write=args.write, check=args.check))
    if args.hitl:
        hitl_demo()
        return
    fault = FAULTS.get(args.fault) if args.fault else None
    if args.pattern:
        run_one(args.pattern, args.loan, fault, trace=True)
        return
    print(f"=== {args.loan} through every pattern" + (f" (fault: {args.fault})" if fault else ""))
    for p in PATTERNS:
        run_one(p, args.loan, fault, trace=False)
    print("\n=== per-agent trace: supervisor")
    run_one("supervisor", args.loan, fault, trace=True)


if __name__ == "__main__":
    main()
