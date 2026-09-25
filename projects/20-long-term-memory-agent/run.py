"""Convenience entry point: `python projects/20-long-term-memory-agent/run.py`."""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[1])]  # project pkg + repo root (shared/)

from memory_agent.demo import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
