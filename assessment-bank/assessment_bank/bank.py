"""Load the YAML question bank. One file per course module, answers stay server-side."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, model_validator

MODULE_ORDER: tuple[str, ...] = (
    "foundations",
    "frameworks-orchestration",
    "llm-core",
    "rag-stack",
    "agentic-core",
    "trust-quality",
    "customization",
    "production-deployment",
)

PASS_RATIO = 0.7


class Choice(BaseModel):
    id: str
    text: str


class Question(BaseModel):
    id: str
    type: Literal["single", "multi"]
    prompt: str
    choices: list[Choice]
    points: int = Field(default=1, ge=1)
    explanation: str
    answer: str | None = None
    answers: list[str] | None = None

    @model_validator(mode="after")
    def _keys_match_choices(self) -> Question:
        ids = {c.id for c in self.choices}
        if len(ids) != len(self.choices):
            raise ValueError(f"{self.id}: duplicate choice id")
        if self.type == "single":
            if not self.answer or self.answer not in ids or self.answers:
                raise ValueError(f"{self.id}: single questions need one answer id")
        elif not self.answers or len(set(self.answers)) != len(self.answers):
            raise ValueError(f"{self.id}: multi questions need a set of answer ids")
        elif set(self.answers) - ids or self.answer:
            raise ValueError(f"{self.id}: multi answers must be choice ids")
        return self

    def correct_ids(self) -> list[str]:
        if self.type == "single":
            return [self.answer or ""]
        return sorted(self.answers or [])

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type,
            "prompt": self.prompt,
            "points": self.points,
            "choices": [{"id": c.id, "text": c.text} for c in self.choices],
        }


class Lab(BaseModel):
    id: str
    title: str
    prompt: str
    tests: str
    points: int = Field(default=3, ge=1)
    timeout_seconds: int = Field(default=5, ge=1, le=30)

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "prompt": self.prompt,
            "points": self.points,
            "timeout_seconds": self.timeout_seconds,
        }


class Module(BaseModel):
    id: str
    title: str
    questions: list[Question]
    labs: list[Lab]

    @model_validator(mode="after")
    def _unique_ids(self) -> Module:
        qids = [q.id for q in self.questions]
        lids = [lab.id for lab in self.labs]
        if len(qids) < 3:
            raise ValueError(f"{self.id}: need at least 3 questions")
        if len(set(qids)) != len(qids) or len(set(lids)) != len(lids):
            raise ValueError(f"{self.id}: duplicate question or lab id")
        if not self.labs:
            raise ValueError(f"{self.id}: need at least one lab")
        return self

    def public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "questions": [q.public() for q in self.questions],
            "labs": [lab.public() for lab in self.labs],
        }


def banks_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "banks"


def labs_dir() -> Path:
    return Path(__file__).resolve().parents[1] / "labs"


def load_modules(path: Path | None = None) -> list[Module]:
    path = path or banks_dir()
    found: dict[str, Module] = {}
    for file in sorted(path.glob("*.yaml")):
        raw = yaml.safe_load(file.read_text())
        module = Module.model_validate(raw)
        if module.id != file.stem:
            raise ValueError(f"{file.name} declares id {module.id}")
        found[module.id] = module
    missing = [name for name in MODULE_ORDER if name not in found]
    extra = [name for name in found if name not in MODULE_ORDER]
    if missing or extra:
        raise ValueError(f"question bank modules missing={missing} extra={extra}")
    return [found[name] for name in MODULE_ORDER]
