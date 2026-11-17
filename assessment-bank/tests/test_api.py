"""Signed-in quiz, lab and progress flow against the in-memory store."""

from fastapi.testclient import TestClient

from assessment_bank.app import create_app
from assessment_bank.bank import load_modules

AUTH = {"Authorization": "Bearer ada"}


def _client():
    return TestClient(create_app())


def test_health_is_open_and_modules_are_not():
    client = _client()
    assert client.get("/healthz").json()["store"] == "memory"
    assert client.get("/modules").status_code == 401
    assert client.get("/modules", headers={"Authorization": "Bearer bad id"}).status_code == 401


def test_quiz_lab_and_progress():
    client = _client()
    module = load_modules()[0]
    answers = {}
    for question in module.questions:
        if question.type == "single":
            answers[question.id] = question.answer
        else:
            answers[question.id] = list(question.answers)
    quiz = client.post("/modules/foundations/quiz", headers=AUTH, json={"answers": answers})
    assert quiz.status_code == 200
    assert quiz.json()["passed"] is True
    code = (
        "def estimate_tokens(text):\n"
        "    if not text:\n"
        "        return 0\n"
        "    return max(1, len(text) // 4)\n"
    )
    lab = client.post(
        "/modules/foundations/labs/foundations-lab-tokens",
        headers=AUTH,
        json={"code": code},
    )
    assert lab.status_code == 200 and lab.json()["passed"] is True
    progress = client.get("/progress", headers=AUTH).json()
    row = next(item for item in progress["modules"] if item["id"] == "foundations")
    assert row["complete"] is True
    assert row["quiz_best"] == 1
    other = client.get("/progress", headers={"Authorization": "Bearer grace"}).json()
    assert all(item["quiz_best"] is None for item in other["modules"])
