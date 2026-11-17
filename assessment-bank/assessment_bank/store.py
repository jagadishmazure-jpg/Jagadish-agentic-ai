"""Learner progress. Memory for local runs and tests; Cosmos DB when configured."""

from __future__ import annotations

import json
import os
import threading
import uuid
from datetime import UTC, datetime
from email.utils import formatdate
from typing import Any, Protocol

from pydantic import BaseModel, Field

from assessment_bank.grading import LabGrade, QuizGrade


class Attempt(BaseModel):
    id: str
    learner_id: str
    module_id: str
    kind: str
    item_id: str
    score: float
    points: int
    max_points: int
    passed: bool
    submitted_at: str
    detail: dict[str, Any] = Field(default_factory=dict)


class ProgressStore(Protocol):
    def save(self, attempt: Attempt) -> Attempt:
        """Persist one attempt and return it."""

    def list_for(self, learner_id: str) -> list[Attempt]:
        """Return the attempts stored for this learner."""


class MemoryStore:
    def __init__(self) -> None:
        self._rows: list[Attempt] = []
        self._lock = threading.Lock()

    def save(self, attempt: Attempt) -> Attempt:
        with self._lock:
            self._rows.append(attempt)
        return attempt

    def list_for(self, learner_id: str) -> list[Attempt]:
        with self._lock:
            return [row for row in self._rows if row.learner_id == learner_id]


Transport = Any


class CosmosStore:
    """Data-plane REST client. AAD token, no account key. ``transport`` is injectable."""

    def __init__(
        self,
        endpoint: str,
        database: str,
        container: str,
        token_provider,
        transport=None,
    ):
        self.endpoint = endpoint.rstrip("/")
        self.database = database
        self.container = container
        self.token_provider = token_provider
        self.transport = transport or _http_transport

    def _headers(self, learner_id: str, *, query: bool) -> dict[str, str]:
        headers = {
            "Authorization": f"type=aad&ver=1.0&sig={self.token_provider()}",
            "x-ms-version": "2018-12-31",
            "x-ms-date": formatdate(usegmt=True),
            "x-ms-documentdb-partitionkey": json.dumps([learner_id]),
            "Accept": "application/json",
        }
        if query:
            headers["Content-Type"] = "application/query+json"
            headers["x-ms-documentdb-isquery"] = "True"
        else:
            headers["Content-Type"] = "application/json"
        return headers

    def _docs(self) -> str:
        return f"{self.endpoint}/dbs/{self.database}/colls/{self.container}/docs"

    def save(self, attempt: Attempt) -> Attempt:
        document = attempt.model_dump()
        document["learnerId"] = attempt.learner_id
        status, _body = self.transport(
            "POST", self._docs(), self._headers(attempt.learner_id, query=False), document
        )
        if status >= 300:
            raise RuntimeError(f"cosmos upsert failed: {status}")
        return attempt

    def list_for(self, learner_id: str) -> list[Attempt]:
        query = {
            "query": "SELECT * FROM c WHERE c.learnerId = @learner",
            "parameters": [{"name": "@learner", "value": learner_id}],
        }
        status, body = self.transport(
            "POST", self._docs(), self._headers(learner_id, query=True), query
        )
        if status >= 300:
            raise RuntimeError(f"cosmos query failed: {status}")
        return [Attempt.model_validate(doc) for doc in body.get("Documents", [])]


def _http_transport(method: str, url: str, headers: dict[str, str], body: dict) -> tuple[int, dict]:
    import httpx

    response = httpx.request(method, url, headers=headers, json=body, timeout=10)
    payload = response.json() if response.content else {}
    return response.status_code, payload


def azure_token() -> str:
    try:
        from azure.identity import DefaultAzureCredential
    except ImportError as exc:  # pragma: no cover - optional extra
        raise RuntimeError("azure-identity is not installed. Run: uv sync --extra openai") from exc
    return DefaultAzureCredential().get_token("https://cosmos.azure.com/.default").token


def new_attempt(
    *,
    learner_id: str,
    module_id: str,
    kind: str,
    item_id: str,
    score: float,
    points: int,
    max_points: int,
    passed: bool,
    detail: dict[str, Any],
) -> Attempt:
    return Attempt(
        id=str(uuid.uuid4()),
        learner_id=learner_id,
        module_id=module_id,
        kind=kind,
        item_id=item_id,
        score=score,
        points=points,
        max_points=max_points,
        passed=passed,
        submitted_at=datetime.now(UTC).isoformat(),
        detail=detail,
    )


def from_quiz(learner_id: str, module_id: str, grade: QuizGrade) -> Attempt:
    return new_attempt(
        learner_id=learner_id,
        module_id=module_id,
        kind="quiz",
        item_id=module_id,
        score=grade.score,
        points=grade.points,
        max_points=grade.max_points,
        passed=grade.passed,
        detail={"items": grade.items},
    )


def from_lab(learner_id: str, module_id: str, lab_id: str, grade: LabGrade) -> Attempt:
    return new_attempt(
        learner_id=learner_id,
        module_id=module_id,
        kind="lab",
        item_id=lab_id,
        score=1.0 if grade.passed else 0.0,
        points=grade.points,
        max_points=grade.max_points,
        passed=grade.passed,
        detail={"summary": grade.summary},
    )


def store_from_env(env: dict[str, str] | None = None) -> ProgressStore:
    env = dict(os.environ) if env is None else env
    if env.get("ASSESSMENT_STORE", "memory").strip().lower() != "cosmos":
        return MemoryStore()
    endpoint = env.get("COSMOS_ENDPOINT", "").strip()
    database = env.get("COSMOS_DATABASE", "").strip()
    container = env.get("COSMOS_CONTAINER", "").strip()
    if not (endpoint and database and container):
        raise RuntimeError("ASSESSMENT_STORE=cosmos needs COSMOS_ENDPOINT, DATABASE and CONTAINER")
    return CosmosStore(endpoint, database, container, azure_token)
