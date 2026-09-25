"""Eval gate: `python projects/08-contract-review/evals/run_eval.py [--min-precision 0.8]`.

Exits non-zero when metrics fall below thresholds, so it can gate CI / prompt changes.
"""

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parents[2])]

from contract_review.evaluation import format_report, gate, run_eval  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--min-precision", type=float, default=0.80)
    parser.add_argument("--min-recall", type=float, default=0.80)
    args = parser.parse_args()
    res = run_eval()
    print(format_report(res))
    ok, reasons = gate(res, args.min_precision, args.min_recall)
    print(
        f"\nGATE {'PASS' if ok else 'FAIL'} (min precision {args.min_precision}, "
        f"min recall {args.min_recall})" + ("" if ok else f": {'; '.join(reasons)}")
    )
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
