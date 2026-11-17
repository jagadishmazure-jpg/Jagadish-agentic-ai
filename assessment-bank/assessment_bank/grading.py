"""Auto-grade quizzes and pytest labs.

Lab submissions run in a temporary directory with a short timeout. That is enough for
these exercises and for CI. It is not a security sandbox: a deployed grader should run
each submission in its own container.
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from pydantic import BaseModel, Field

from assessment_bank.bank import PASS_RATIO, Lab, Module

MAX_CODE_BYTES = 16_000


class QuizGrade(BaseModel):
    score: float
    points: int
    max_points: int
    passed: bool
    items: list[dict[str, object]]


class LabGrade(BaseModel):
    passed: bool
    points: int
    max_points: int
    summary: str = Field(max_length=4000)


def grade_quiz(module: Module, answers: dict[str, str | list[str]]) -> QuizGrade:
    expected = {q.id for q in module.questions}
    unknown = sorted(set(answers) - expected)
    missing = sorted(expected - set(answers))
    if unknown or missing:
        raise ValueError(f"unknown={unknown} missing={missing}")
    points = 0
    max_points = 0
    items: list[dict[str, object]] = []
    for question in module.questions:
        max_points += question.points
        given = answers[question.id]
        if question.type == "single":
            ok = isinstance(given, str) and given == question.answer
        else:
            ok = isinstance(given, list) and sorted(given) == question.correct_ids()
        if ok:
            points += question.points
        items.append(
            {
                "id": question.id,
                "correct": ok,
                "expected": question.correct_ids(),
                "explanation": question.explanation,
            }
        )
    score = points / max_points
    return QuizGrade(
        score=round(score, 4),
        points=points,
        max_points=max_points,
        passed=score >= PASS_RATIO,
        items=items,
    )


def _fail(lab: Lab, summary: str) -> LabGrade:
    return LabGrade(passed=False, points=0, max_points=lab.points, summary=summary[:4000])


def grade_lab(lab: Lab, code: str, labs: Path) -> LabGrade:
    if len(code.encode()) > MAX_CODE_BYTES:
        return _fail(lab, "submission is too large")
    if "\x00" in code:
        return _fail(lab, "submission contains a null byte")
    try:
        ast.parse(code)
    except SyntaxError as exc:
        return _fail(lab, f"syntax error: {exc}")
    test_path = (labs / lab.tests).resolve()
    root = labs.resolve()
    if root != test_path and root not in test_path.parents:
        raise ValueError(f"lab test {lab.tests} escapes {root}")
    if not test_path.is_file():
        raise ValueError(f"missing lab test {lab.tests}")
    try:
        with tempfile.TemporaryDirectory(prefix="assessment-lab-") as tmp:
            dest = Path(tmp)
            (dest / "solution.py").write_text(code)
            (dest / "test_lab.py").write_text(test_path.read_text())
            try:
                proc = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pytest",
                        "test_lab.py",
                        "-q",
                        "--tb=line",
                        "-p",
                        "no:cacheprovider",
                        "--noconftest",
                    ],
                    cwd=dest,
                    capture_output=True,
                    text=True,
                    timeout=lab.timeout_seconds,
                    env={
                        "PATH": os.environ.get("PATH", ""),
                        "PYTHONDONTWRITEBYTECODE": "1",
                        "PYTHONPATH": str(dest),
                        "LLM_PROVIDER": "mock",
                    },
                    check=False,
                )
            except subprocess.TimeoutExpired:
                return _fail(lab, f"timed out after {lab.timeout_seconds}s")
            summary = (proc.stdout + "\n" + proc.stderr).strip()
            passed = proc.returncode == 0
            return LabGrade(
                passed=passed,
                points=lab.points if passed else 0,
                max_points=lab.points,
                summary=summary[-4000:],
            )
    except OSError as exc:
        return _fail(lab, f"could not run pytest: {exc}")
