"""The README comparison block and evals/comparison.json must match a fresh runner output."""

import json

import pytest

from orchestration_lab import compare


@pytest.fixture(scope="module")
def results():
    from shared import resilience

    resilience.SLEEP_SCALE = 0.0
    return compare.run_comparison()


def test_readme_table_matches_runner_output(results):
    readme = compare.README.read_text()
    assert compare.START in readme and compare.END in readme
    assert compare.readme_with(readme, compare.render(results)) == readme, (
        "README comparison block is stale: run `python run.py --compare --write`"
    )


def test_comparison_json_matches_runner_output(results):
    assert json.loads(compare.OUT.read_text()) == results


def test_runner_is_deterministic(results):
    again = compare.run_comparison()
    assert again == results


def test_no_pattern_completes_a_wrong_decision_under_faults(results):
    cells = [c for row in results["faults"].values() for c in row.values()]
    assert all(c["outcome"] != "UNSAFE" for c in cells)
    assert all(c["filed"] == 0 for c in cells if c["outcome"].startswith("safe stop"))


def test_no_policy_violations_in_any_pattern(results):
    assert all(r["policy_violations"] == 0 for r in results["patterns"])
