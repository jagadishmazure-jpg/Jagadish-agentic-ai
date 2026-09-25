"""Offline eval harness: golden JSONL per project -> metrics -> thresholds (promotion gate)."""

from shared.evals.harness import (
    METRICS,
    CaseResult,
    EvalReport,
    check_thresholds,
    load_golden,
    run_suite,
)

__all__ = ["METRICS", "CaseResult", "EvalReport", "check_thresholds", "load_golden", "run_suite"]
