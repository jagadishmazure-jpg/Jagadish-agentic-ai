"""Eval harness.

Each project ships ``evals/golden.jsonl`` (one case per line: ``id``, ``input``, ``expect``)
and a ``run_case(case) -> CaseResult`` in its package. The harness runs every case, measures
cost and tool calls from telemetry deltas, and aggregates:

* ``task_success``          - fraction of cases whose outcome matched ``expect``
* ``groundedness``          - mean citation coverage / grounded score (cases that produce text)
* ``policy_violation_rate`` - fraction of cases that violated a policy / guardrail
* ``tool_error_rate``       - tool errors / tool calls through the gateway
* ``cost_per_task``         - mean USD per case (token estimate x price table)

Thresholds such as ``{"task_success": ">=0.9", "policy_violation_rate": "<=0"}`` gate
promotion; the ``python -m evals`` runner exits non-zero on any regression.
"""

from __future__ import annotations

import json
import operator
import re
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from shared.observability import telemetry

METRICS = (
    "task_success",
    "groundedness",
    "policy_violation_rate",
    "tool_error_rate",
    "cost_per_task",
)


@dataclass
class CaseResult:
    case_id: str
    success: bool
    grounded: float | None = None
    policy_violation: bool = False
    tool_calls: int | None = None
    tool_errors: int | None = None
    cost_usd: float | None = None
    detail: str = ""


@dataclass
class EvalReport:
    project: str
    cases: list[CaseResult]
    metrics: dict[str, float]
    thresholds: dict[str, str] = field(default_factory=dict)
    violations: list[str] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def passed(self) -> bool:
        return not self.violations

    def failures(self) -> list[CaseResult]:
        return [c for c in self.cases if not c.success or c.policy_violation]

    def to_json(self) -> dict[str, Any]:
        return {
            "project": self.project,
            "n": len(self.cases),
            "metrics": {k: None if v is None else round(v, 6) for k, v in self.metrics.items()},
            "thresholds": self.thresholds,
            "passed": self.passed,
            "violations": self.violations,
            "failed_cases": [c.case_id for c in self.failures()],
        }


def load_golden(path: Path) -> list[dict[str, Any]]:
    cases = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    ids = [c["id"] for c in cases]
    if len(ids) != len(set(ids)):
        raise ValueError(f"duplicate case ids in {path}")
    return cases


def run_suite(
    project: str,
    cases: list[dict[str, Any]],
    run_case: Callable[[dict[str, Any]], CaseResult],
    thresholds: dict[str, str] | None = None,
) -> EvalReport:
    t = telemetry()
    results: list[CaseResult] = []
    start = time.perf_counter()
    for case in cases:
        c0, s0 = t.cost.usd, t.tools.snapshot()
        try:
            r = run_case(case)
        except Exception as exc:  # a crash is a failed case, not a crashed eval
            r = CaseResult(case["id"], False, detail=f"crash: {type(exc).__name__}: {exc}")
        s1 = t.tools.snapshot()
        if r.cost_usd is None:
            r.cost_usd = t.cost.usd - c0
        if r.tool_calls is None:
            r.tool_calls = s1["calls"] - s0["calls"]
        if r.tool_errors is None:
            r.tool_errors = s1["errors"] - s0["errors"]
        results.append(r)
    n = len(results) or 1
    grounded = [r.grounded for r in results if r.grounded is not None]
    calls = sum(r.tool_calls or 0 for r in results)
    metrics = {
        "task_success": sum(r.success for r in results) / n,
        "groundedness": (sum(grounded) / len(grounded)) if grounded else None,  # n/a
        "policy_violation_rate": sum(r.policy_violation for r in results) / n,
        "tool_error_rate": (sum(r.tool_errors or 0 for r in results) / calls) if calls else 0.0,
        "cost_per_task": sum(r.cost_usd or 0.0 for r in results) / n,
    }
    report = EvalReport(
        project, results, metrics, dict(thresholds or {}), seconds=time.perf_counter() - start
    )
    report.violations = check_thresholds(metrics, report.thresholds)
    return report


_OPS = {">=": operator.ge, "<=": operator.le, ">": operator.gt, "<": operator.lt, "==": operator.eq}


def check_thresholds(metrics: dict[str, float | None], thresholds: dict[str, str]) -> list[str]:
    out = []
    for name, rule in thresholds.items():
        m = re.fullmatch(r"\s*(>=|<=|==|>|<)\s*([0-9.eE+-]+)\s*", str(rule))
        if not m or name not in metrics:
            out.append(f"bad threshold {name}: {rule}")
            continue
        op, bound = m.group(1), float(m.group(2))
        if metrics[name] is None:
            out.append(f"{name} is n/a (no case produced a scorable value) but has a threshold")
            continue
        if not _OPS[op](metrics[name], bound):
            out.append(f"{name} = {metrics[name]:.4f} violates {op} {bound}")
    return out


def case_results_json(report: EvalReport) -> list[dict[str, Any]]:
    return [asdict(c) for c in report.cases]
