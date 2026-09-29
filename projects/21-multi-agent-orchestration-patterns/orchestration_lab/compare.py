"""Comparison runner: every pattern, the same golden cases, the same eval pipeline.

For each pattern it runs the business cases from ``evals/golden.jsonl`` through
``shared.evals.run_suite`` (the harness behind ``python -m evals``) and aggregates quality,
groundedness, policy violations, LLM calls, estimated tokens, tool calls, agent turns and the
simulated critical-path latency. It then runs each pattern under three injected faults on one
case (analyst down, a reviewer that is never satisfied, a bad handoff) and classifies the
behaviour: recovered, safe stop (referral with a reason), unsafe (wrong decision completed) or
n/a (the pattern never asks a model for a route, so a bad handoff cannot happen).

    python run.py --compare            # print the tables
    python run.py --compare --write    # refresh evals/comparison.json and the README block
    python run.py --compare --check    # exit 1 if either is stale (CI / tests)

The README table is generated only from this runner; ``tests/test_comparison.py`` fails if the
README or ``comparison.json`` drift from a fresh run.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from orchestration_lab import eval_suite
from orchestration_lab.graph import PATTERNS
from orchestration_lab.harness import BOGUS_TARGET
from shared.evals import CaseResult, load_golden, run_suite

HERE = Path(__file__).resolve().parents[1]
GOLDEN = HERE / "evals" / "golden.jsonl"
OUT = HERE / "evals" / "comparison.json"
README = HERE / "README.md"
START, END = "<!-- comparison:start -->", "<!-- comparison:end -->"
FAULT_CASE = "L-2101"
FAULTS = {
    "analyst_down": {"down": "analyst"},
    "looping_reviewer": {"loop": True},
    "bad_handoff": {"bad_handoff": True},
}


def business_cases() -> list[dict[str, Any]]:
    return [c for c in load_golden(GOLDEN) if "business" in c.get("tags", [])]


def _pattern_row(pattern: str, cases: list[dict[str, Any]]) -> dict[str, Any]:
    per_case: dict[str, dict[str, Any]] = {}

    def run_case(case: dict[str, Any]) -> CaseResult:
        r, s = eval_suite.run(case["input"], pattern)
        final = r.get("final") or {}
        ok, grounded, _checks = eval_suite.score_final(case, r)
        per_case[case["id"]] = {**final.get("metrics", {}), "ok": ok}
        return CaseResult(
            case["id"],
            ok,
            grounded,
            eval_suite.violations(final, s, False),
            detail=f"{final.get('decision')} / {final.get('stop_reason')}",
        )

    report = run_suite(f"21/{pattern}", cases, run_case)
    n = len(cases)

    def avg(key: str) -> float:
        return sum(per_case[c["id"]][key] for c in cases) / n

    return {
        "pattern": pattern,
        "n": n,
        "quality": round(report.metrics["task_success"], 4),
        "groundedness": round(report.metrics["groundedness"] or 0.0, 4),
        "policy_violations": round(report.metrics["policy_violation_rate"], 4),
        "avg_llm_calls": round(avg("llm_calls"), 2),
        "avg_tokens": round(avg("tokens")),
        "avg_tool_calls": round(avg("tool_calls"), 2),
        "avg_turns": round(avg("turns"), 2),
        "avg_latency_s": round(avg("sim_latency_ms") / 1000, 2),
        "failed_cases": sorted(c.case_id for c in report.failures()),
    }


def _fault_cell(pattern: str, fault: str) -> dict[str, Any]:
    r, s = eval_suite.run({"loan_id": FAULT_CASE, "fault_plan": FAULTS[fault]}, pattern)
    final = r.get("final") or {}
    metrics = final.get("metrics", {})
    fired = fault != "bad_handoff" or any(BOGUS_TARGET in e["reason"] for e in r.get("exits", []))
    correct = eval_suite.correct_decision(FAULT_CASE)
    if not fired:
        outcome = "n/a"
    elif final.get("stop_reason") == "completed":
        outcome = "recovered" if final.get("decision") == correct else "UNSAFE"
    else:
        outcome = f"safe stop: {final.get('stop_reason')}"
    return {
        "outcome": outcome,
        "turns": metrics.get("turns", 0),
        "llm_calls": metrics.get("llm_calls", 0),
        "tokens": metrics.get("tokens", 0),
        "filed": len(s.filed),
    }


def run_comparison() -> dict[str, Any]:
    cases = business_cases()
    rows = [_pattern_row(p, cases) for p in PATTERNS]
    faults = {p: {f: _fault_cell(p, f) for f in FAULTS} for p in PATTERNS}
    return {
        "golden_cases": [c["id"] for c in cases],
        "fault_case": FAULT_CASE,
        "patterns": rows,
        "faults": faults,
    }


def render(results: dict[str, Any]) -> str:
    L = [
        f"Business cases: {len(results['golden_cases'])} (every `business` case in "
        "`evals/golden.jsonl`), offline deterministic mock model. Tokens are estimates "
        "(characters / 4); latency is **simulated** from the harness latency model "
        "(critical path, parallel branches overlap), not a measurement.",
        "",
        "| Pattern | Quality (task success) | Grounded | Policy viol. | LLM calls / case "
        "| Est. tokens / case | Tool calls / case | Agent turns / case "
        "| Sim. latency / case (s) | Failed cases |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in results["patterns"]:
        failed = ", ".join(f"`{c}`" for c in r["failed_cases"]) or "none"
        L.append(
            f"| {r['pattern']} | {r['quality']:.2f} | {r['groundedness']:.2f} | "
            f"{r['policy_violations']:.2f} | {r['avg_llm_calls']:.1f} | {r['avg_tokens']:,} | "
            f"{r['avg_tool_calls']:.1f} | {r['avg_turns']:.1f} | {r['avg_latency_s']:.1f} | "
            f"{failed} |"
        )
    L += [
        "",
        f"Failure behaviour on `{results['fault_case']}` (cell: outcome · agent turns · LLM "
        "calls before the run ended; *recovered* = correct decision completed, *safe stop* = "
        "referral with a reason and nothing filed, *UNSAFE* = wrong decision completed):",
        "",
        "| Pattern | Analyst down | Looping reviewer | Bad handoff |",
        "|---|---|---|---|",
    ]
    for p, cells in results["faults"].items():
        row = [
            f"{c['outcome']} · {c['turns']} turns · {c['llm_calls']} calls"
            if c["outcome"] != "n/a"
            else "n/a (no model-chosen routes)"
            for c in cells.values()
        ]
        L.append(f"| {p} | " + " | ".join(row) + " |")
    return "\n".join(L)


def readme_with(readme: str, table: str) -> str:
    head, _, rest = readme.partition(START)
    _, _, tail = rest.partition(END)
    return f"{head}{START}\n{table}\n{END}{tail}"


def main(write: bool = False, check: bool = False) -> int:
    results = run_comparison()
    table = render(results)
    print(table)
    readme = README.read_text()
    fresh_json = json.dumps(results, indent=2) + "\n"
    if write:
        OUT.write_text(fresh_json)
        README.write_text(readme_with(readme, table))
        print(f"\nwrote {OUT.name} and the README comparison block")
    if check:
        stale = []
        if not OUT.exists() or OUT.read_text() != fresh_json:
            stale.append(str(OUT.name))
        if readme_with(readme, table) != readme:
            stale.append("README.md comparison block")
        if stale:
            print(f"\nSTALE: {stale}; run `python run.py --compare --write`")
            return 1
    return 0
