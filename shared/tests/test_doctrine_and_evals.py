"""Promotion gate: every project card validates, covers every graph node with a five-exit
row, has >= 10 golden cases and passing scores, and DOCTRINE.md is regenerated."""

import shutil

import pytest
import yaml

from shared.doctrine import project_dirs, render_card, validate_project
from shared.evals import CaseResult, check_thresholds, run_suite

PROJECTS = project_dirs()


@pytest.mark.parametrize("project", PROJECTS, ids=lambda p: p.name)
def test_promotion_gate(project):
    assert validate_project(project) == []
    assert (project / "DOCTRINE.md").read_text() == render_card(project), (
        "DOCTRINE.md stale: run `python -m shared.doctrine render`"
    )


def test_gate_rejects_incomplete_cards(tmp_path):
    if not PROJECTS:
        pytest.skip("no doctrine cards yet")
    src = PROJECTS[0]
    dst = tmp_path / src.name
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "tests"))
    card = yaml.safe_load((dst / "doctrine.yaml").read_text())
    for field in ("owner", "kpis", "stop_conditions"):
        broken = {k: v for k, v in card.items() if k != field}
        (dst / "doctrine.yaml").write_text(yaml.safe_dump(broken))
        problems = validate_project(dst)
        assert problems and field in problems[0]
    broken = dict(card, failure_playbook=card["failure_playbook"][1:])
    (dst / "doctrine.yaml").write_text(yaml.safe_dump(broken))
    assert any("without a five-exit row" in p for p in validate_project(dst, False))
    broken = dict(card, planes={**card["planes"], "knowledge": ""})
    (dst / "doctrine.yaml").write_text(yaml.safe_dump(broken))
    assert "plane dependencies missing" in validate_project(dst)[0]


def test_thresholds_and_harness_metrics():
    assert check_thresholds({"task_success": 0.8}, {"task_success": ">=0.9"})
    assert not check_thresholds({"cost_per_task": 0.001}, {"cost_per_task": "<=0.01"})
    report = run_suite(
        "x",
        [{"id": "a"}, {"id": "b"}],
        lambda c: CaseResult(
            c["id"], c["id"] == "a", grounded=1.0, policy_violation=c["id"] == "b"
        ),
        {"task_success": ">=0.5", "policy_violation_rate": "<=0"},
    )
    assert report.metrics["task_success"] == 0.5
    assert report.violations == ["policy_violation_rate = 0.5000 violates <= 0.0"]


def test_every_project_carries_a_doctrine_card():
    from shared.doctrine.card import ROOT

    folders = sorted(p for p in (ROOT / "projects").iterdir() if p.is_dir())
    assert folders and [p.name for p in folders] == [p.name for p in PROJECTS]


def test_readme_compliance_matrix_is_fresh():
    from shared.doctrine.card import MATRIX_START, ROOT, readme_with_matrix

    readme = (ROOT / "README.md").read_text()
    assert MATRIX_START in readme
    assert readme == readme_with_matrix(readme), "run `python -m shared.doctrine render`"
