"""Convenience entry point: `python projects/16-telecom-outage-care/run.py` from anywhere."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1])]  # project pkg + repo root (shared/)

from outage_care.demo import main  # noqa: E402

if __name__ == "__main__":
    main()
