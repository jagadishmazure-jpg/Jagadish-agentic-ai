"""Run every project's golden eval suite offline and gate on thresholds.

    python -m evals                 # all projects, writes projects/*/evals/scores.json
    python -m evals --project 03    # one project
    python -m evals --no-write      # don't update scores.json (CI regression check)

Exits 1 if any project's metrics violate the thresholds in its doctrine.yaml.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from shared.doctrine.card import (  # noqa: E402
    ensure_path,
    load_card,
    project_dirs,
    resolve,
    scores_path,
)
from shared.evals.harness import METRICS, load_golden, run_suite  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--live", action="store_true", help="use the configured real LLM")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)
    if not args.live:
        os.environ["LLM_PROVIDER"] = "mock"
    from shared import resilience

    resilience.SLEEP_SCALE = 0.0
    dirs = [d for d in project_dirs() if not args.project or d.name.startswith(args.project)]
    header = f"{'project':32} {'n':>3} " + " ".join(f"{m[:14]:>14}" for m in METRICS) + "  gate"
    print(header)
    print("-" * len(header))
    failed = 0
    for d in dirs:
        card = load_card(d / "doctrine.yaml")
        ensure_path(d)
        cases = load_golden(d / card.eval.golden)
        report = run_suite(card.project, cases, resolve(card.eval.suite), card.eval.thresholds)
        m = report.metrics
        cells = " ".join(
            f"{m[k]:>14.5f}" if k == "cost_per_task" else f"{m[k]:>14.2f}" for k in METRICS
        )
        print(f"{card.project:32} {len(cases):>3} {cells}  {'PASS' if report.passed else 'FAIL'}")
        for v in report.violations:
            print(f"    ! {v}")
        if args.verbose or not report.passed:
            for c in report.failures():
                print(
                    f"    - {c.case_id}: success={c.success} "
                    f"violation={c.policy_violation} {c.detail}"
                )
        if not args.no_write:
            scores_path(d).parent.mkdir(exist_ok=True)
            scores_path(d).write_text(json.dumps(report.to_json(), indent=2) + "\n")
        failed += not report.passed
    print(f"\neval gate: {len(dirs) - failed}/{len(dirs)} projects pass")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
