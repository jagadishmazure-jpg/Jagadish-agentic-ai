"""The eight course modules load, and the HTTP API does not leak answer keys."""

from fastapi.testclient import TestClient

from assessment_bank.app import create_app
from assessment_bank.bank import MODULE_ORDER, load_modules
from assessment_bank.grading import grade_quiz

AUTH = {"Authorization": "Bearer ada"}


def test_course_modules_and_hidden_answers():
    modules = load_modules()
    assert [module.id for module in modules] == list(MODULE_ORDER)
    client = TestClient(create_app(modules=modules))
    listed = client.get("/modules", headers=AUTH)
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == list(MODULE_ORDER)
    for module in modules:
        body = client.get(f"/modules/{module.id}", headers=AUTH).json()
        for question in body["questions"]:
            assert "answer" not in question
            assert "answers" not in question
            assert "explanation" not in question
        assert body["labs"] and "tests" not in body["labs"][0]


def test_foundations_quiz_scores():
    module = load_modules()[0]
    perfect = {}
    for question in module.questions:
        if question.type == "single":
            perfect[question.id] = question.answer
        else:
            perfect[question.id] = list(question.answers)
    grade = grade_quiz(module, perfect)
    assert grade.passed and grade.score == 1
    wrong = dict(perfect)
    wrong["foundations-q1"] = "a"
    missed = grade_quiz(module, wrong)
    assert not missed.passed or missed.score < 1
    assert missed.items[0]["correct"] is False


def test_quiz_requires_every_question():
    module = load_modules()[0]
    try:
        grade_quiz(module, {})
    except ValueError as exc:
        assert "missing" in str(exc)
    else:
        raise AssertionError("empty answers should fail")
