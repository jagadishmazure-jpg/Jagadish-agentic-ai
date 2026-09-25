"""python -m shared.doctrine validate|render [--check] [--project 03]

validate: promotion gate - every card complete, every graph node has a five-exit row,
          golden set >= 10 cases, eval scores present and within thresholds,
          DOCTRINE.md up to date.
render:   regenerate projects/*/DOCTRINE.md from doctrine.yaml + evals/scores.json.
"""

from __future__ import annotations

import argparse
import sys

from shared.doctrine.card import project_dirs, render_card, validate_project


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["validate", "render"])
    ap.add_argument("--project", help="folder prefix, e.g. 03")
    args = ap.parse_args(argv)
    dirs = [d for d in project_dirs() if not args.project or d.name.startswith(args.project)]
    failed = 0
    for d in dirs:
        if args.command == "render":
            (d / "DOCTRINE.md").write_text(render_card(d))
            print(f"rendered {d.name}/DOCTRINE.md")
            continue
        problems = validate_project(d)
        card_md = d / "DOCTRINE.md"
        if not card_md.exists() or card_md.read_text() != render_card(d):
            problems.append("DOCTRINE.md stale: run `python -m shared.doctrine render`")
        status = "PASS" if not problems else "FAIL"
        print(f"[{status}] {d.name}")
        for p in problems:
            print(f"    - {p}")
        failed += bool(problems)
    if args.command == "validate":
        print(f"\npromotion gate: {len(dirs) - failed}/{len(dirs)} projects pass")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
