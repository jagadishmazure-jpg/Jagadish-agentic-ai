"""Assessment bank API.

* ``GET  /healthz``
* ``GET  /modules`` and ``GET /modules/{id}``     questions and labs, without answers
* ``POST /modules/{id}/quiz``                     auto-graded from the YAML bank
* ``POST /modules/{id}/labs/{lab_id}``            auto-graded with pytest
* ``GET  /progress``                              this learner's attempts

Local and tests use a mock bearer token and an in-memory store. A deployment sets
``ASSESSMENT_AUTH_MODE=entra`` and ``ASSESSMENT_STORE=cosmos``.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from assessment_bank.auth import (
    AuthError,
    AuthSettings,
    Principal,
    principal_from_token,
    settings_from_env,
)
from assessment_bank.bank import Module, load_modules
from assessment_bank.grading import grade_lab, grade_quiz
from assessment_bank.store import MemoryStore, ProgressStore, from_lab, from_quiz, store_from_env


class QuizBody(BaseModel):
    answers: dict[str, str | list[str]]


class LabBody(BaseModel):
    code: str = Field(min_length=1, max_length=16_000)


def create_app(
    *,
    modules: list[Module] | None = None,
    store: ProgressStore | None = None,
    auth: AuthSettings | None = None,
) -> FastAPI:
    loaded = modules if modules is not None else load_modules()
    by_id = {module.id: module for module in loaded}
    progress: ProgressStore = store if store is not None else store_from_env()
    settings = auth if auth is not None else settings_from_env()
    app = FastAPI(title="Assessment bank", version="0.1.0")

    def learner(authorization: Annotated[str | None, Header()] = None) -> Principal:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="sign in required")
        token = authorization.split(" ", 1)[1].strip()
        try:
            return principal_from_token(token, settings)
        except AuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc

    def module_or_404(module_id: str) -> Module:
        module = by_id.get(module_id)
        if module is None:
            raise HTTPException(status_code=404, detail=f"unknown module: {module_id}")
        return module

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        backend = "memory" if isinstance(progress, MemoryStore) else "cosmos"
        return {"status": "ok", "auth": settings.mode, "store": backend}

    @app.get("/modules")
    def list_modules(authorization: Annotated[str | None, Header()] = None) -> list[dict[str, Any]]:
        learner(authorization)
        return [
            {
                "id": module.id,
                "title": module.title,
                "questions": len(module.questions),
                "labs": len(module.labs),
            }
            for module in loaded
        ]

    @app.get("/modules/{module_id}")
    def get_module(
        module_id: str, authorization: Annotated[str | None, Header()] = None
    ) -> dict[str, Any]:
        learner(authorization)
        return module_or_404(module_id).public()

    @app.post("/modules/{module_id}/quiz")
    def submit_quiz(
        module_id: str,
        body: QuizBody,
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        user = learner(authorization)
        module = module_or_404(module_id)
        try:
            grade = grade_quiz(module, body.answers)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        attempt = progress.save(from_quiz(user.learner_id, module.id, grade))
        return {"attempt_id": attempt.id, **grade.model_dump()}

    @app.post("/modules/{module_id}/labs/{lab_id}")
    def submit_lab(
        module_id: str,
        lab_id: str,
        body: LabBody,
        authorization: Annotated[str | None, Header()] = None,
    ) -> dict[str, Any]:
        user = learner(authorization)
        module = module_or_404(module_id)
        lab = next((item for item in module.labs if item.id == lab_id), None)
        if lab is None:
            raise HTTPException(status_code=404, detail=f"unknown lab: {lab_id}")
        from assessment_bank.bank import labs_dir

        grade = grade_lab(lab, body.code, labs_dir())
        attempt = progress.save(from_lab(user.learner_id, module.id, lab.id, grade))
        return {"attempt_id": attempt.id, **grade.model_dump()}

    @app.get("/progress")
    def get_progress(authorization: Annotated[str | None, Header()] = None) -> dict[str, Any]:
        user = learner(authorization)
        attempts = progress.list_for(user.learner_id)
        modules_out = []
        for module in loaded:
            mine = [row for row in attempts if row.module_id == module.id]
            quizzes = [row for row in mine if row.kind == "quiz"]
            best = max((row.score for row in quizzes), default=None)
            passed_labs = sorted({row.item_id for row in mine if row.kind == "lab" and row.passed})
            lab_ids = [lab.id for lab in module.labs]
            complete = best is not None and best >= 0.7 and set(lab_ids) <= set(passed_labs)
            modules_out.append(
                {
                    "id": module.id,
                    "quiz_best": best,
                    "labs_passed": passed_labs,
                    "complete": complete,
                }
            )
        return {"learner_id": user.learner_id, "modules": modules_out}

    return app
