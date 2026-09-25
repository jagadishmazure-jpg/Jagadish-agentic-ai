"""Convenience entry point: `python projects/12-agent-control-plane/run.py` from anywhere."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1])]  # project pkg + repo root (shared/)

from control_plane.demo import main  # noqa: E402

if __name__ == "__main__":
    main()
