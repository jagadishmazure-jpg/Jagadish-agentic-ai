"""python -m shared.doctrine validate|render|matrix [--project 03]

validate: promotion gate - every card complete, every graph node has a five-exit row,
          golden set >= 10 cases, eval scores present and within thresholds,
          DOCTRINE.md up to date.
render:   regenerate projects/*/DOCTRINE.md from doctrine.yaml + evals/scores.json
          (and the compliance matrix in the top-level README).
matrix:   print the portfolio compliance matrix.
"""

from __future__ import annotations

import argparse
import sys

from shared.doctrine.card import (
    MATRIX_START,
    ROOT,
    project_dirs,
    readme_with_matrix,
    render_card,
    render_matrix,
    validate_project,
)

README = ROOT / "README.md"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("command", choices=["validate", "render", "matrix"])
    ap.add_argument("--project", help="folder prefix, e.g. 03")
    args = ap.parse_args(argv)
    if args.command == "matrix":
        print(render_matrix())
        return 0
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
    readme = README.read_text()
    has_matrix = MATRIX_START in readme
    if args.command == "render" and has_matrix:
        README.write_text(readme_with_matrix(readme))
        print("rendered README.md compliance matrix")
    if args.command == "validate":
        if not args.project and has_matrix and readme != readme_with_matrix(readme):
            print(
                "[FAIL] README.md compliance matrix stale: run `python -m shared.doctrine render`"
            )
            failed += 1
        print(f"\npromotion gate: {len(dirs) - failed}/{len(dirs)} projects pass")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
