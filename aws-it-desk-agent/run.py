"""CLI for the IT desk playbook agent. Offline mock unless IT_DESK_PROVIDER=bedrock.

python aws-it-desk-agent/run.py
python aws-it-desk-agent/run.py How do I reset a forgotten password?
python aws-it-desk-agent/run.py compare
python aws-it-desk-agent/run.py compare --latency
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(ROOT),
    str(ROOT / "projects" / "01-policy-qa-rag"),
    str(ROOT / "aws-it-desk-agent"),
]


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "compare":
        from it_desk.compare import main as compare_main

        return compare_main(argv[1:])
    from it_desk.agent import ask
    from it_desk.playbook import DEMO_QUESTIONS

    question = " ".join(argv) if argv else DEMO_QUESTIONS[0]
    final = ask(question)["final"]
    print(final["status"])
    print(final["answer"])
    if final.get("citations"):
        print("citations: " + ", ".join(c["id"] for c in final["citations"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
