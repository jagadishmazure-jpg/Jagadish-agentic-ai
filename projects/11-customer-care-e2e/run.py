"""Convenience entry point: `python projects/11-customer-care-e2e/run.py` from anywhere."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1])]  # project pkg + repo root (shared/)

from care_e2e.demo import main  # noqa: E402

if __name__ == "__main__":
    main()
