"""Portfolio API (shared/api): health, catalog, card lookup and an eval run, all offline."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from shared.api.app import create_app
from shared.doctrine.card import project_dirs


@pytest.fixture(scope="module")
def client():
    return TestClient(create_app())


def test_health_and_readiness(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    ready = client.get("/readyz").json()
    assert ready["status"] == "ready"
    assert ready["projects"] == len(project_dirs())
    assert ready["llm_provider"] == "mock"


def test_catalog_lists_every_project(client):
    rows = client.get("/projects").json()
    assert [r["project"] for r in rows] == [d.name for d in project_dirs()]
    assert all(1 <= r["maturity"] <= 5 for r in rows)


def test_project_lookup_by_name_or_number(client):
    by_num = client.get("/projects/02").json()
    by_name = client.get("/projects/02-ticket-triage").json()
    assert by_num == by_name
    assert by_num["eval_thresholds"]
    assert client.get("/projects/99").status_code == 404


def test_eval_run_returns_metrics(client):
    r = client.post("/projects/02/evals", json={"limit": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["project"] == "02-ticket-triage" and body["n"] == 3
    assert {"task_success", "policy_violation_rate"} <= set(body["metrics"])
    assert body["llm_provider"] == "mock"


def test_eval_limit_is_validated(client):
    assert client.post("/projects/02/evals", json={"limit": 0}).status_code == 422
