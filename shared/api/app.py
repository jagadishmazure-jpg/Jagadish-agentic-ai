"""Portfolio API: one FastAPI app that exposes the LangGraph projects over HTTP, so the whole
portfolio can run as a single Azure Container App.

* ``GET  /healthz``                     liveness (no dependencies touched)
* ``GET  /readyz``                      readiness: project cards load, reports the LLM provider
* ``GET  /projects``                    catalog built from every ``projects/*/doctrine.yaml``
* ``GET  /projects/{project}``          one card: summary, maturity, KPIs, eval thresholds
* ``POST /projects/{project}/evals``    run that project's golden eval suite and return metrics

``{project}`` accepts the folder name (``03-refund-agent``) or its number (``03``).
The model defaults to the offline mock. A real deployment (Azure OpenAI / Foundry) is used only
when ``PORTFOLIO_ALLOW_LIVE=1`` and ``LLM_PROVIDER`` is set, which is what the Container App
does once the Terraform stack wires the endpoint and managed identity.

Run locally:  ``uvicorn shared.api.app:create_app --factory --port 8080``
"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from shared.doctrine.card import ensure_path, load_card, project_dirs, resolve
from shared.evals.harness import load_golden, run_suite

_EVAL_LOCK = threading.Lock()  # graphs share process-wide fault/telemetry state: one run at a time


class EvalRequest(BaseModel):
    limit: int | None = Field(default=None, ge=1, le=200, description="first N golden cases")


def _live_allowed() -> bool:
    return os.environ.get("PORTFOLIO_ALLOW_LIVE") == "1"


def _find(project: str) -> Path:
    for d in project_dirs():
        if d.name == project or d.name.split("-", 1)[0] == project:
            return d
    raise HTTPException(status_code=404, detail=f"unknown project: {project}")


def _summary(d: Path) -> dict[str, Any]:
    card = load_card(d / "doctrine.yaml")
    return {
        "project": card.project,
        "title": card.title,
        "industry": card.industry,
        "maturity": card.maturity.level,
    }


def create_app() -> FastAPI:
    if not _live_allowed():
        os.environ["LLM_PROVIDER"] = "mock"
    app = FastAPI(title="Agentic AI portfolio API", version="0.1.0")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz")
    def readyz() -> dict[str, Any]:
        n = len(project_dirs())
        if n == 0:
            raise HTTPException(status_code=503, detail="no project cards found")
        return {
            "status": "ready",
            "projects": n,
            "llm_provider": os.environ.get("LLM_PROVIDER", "mock"),
        }

    @app.get("/projects")
    def projects() -> list[dict[str, Any]]:
        return [_summary(d) for d in project_dirs()]

    @app.get("/projects/{project}")
    def project(project: str) -> dict[str, Any]:
        d = _find(project)
        card = load_card(d / "doctrine.yaml")
        return {
            **_summary(d),
            "summary": card.summary,
            "kpis": [k.model_dump() for k in card.kpis],
            "eval_thresholds": card.eval.thresholds,
        }

    @app.post("/projects/{project}/evals")
    def run_evals(project: str, req: EvalRequest | None = None) -> dict[str, Any]:
        d = _find(project)
        card = load_card(d / "doctrine.yaml")
        ensure_path(d)
        cases = load_golden(d / card.eval.golden)
        if req and req.limit:
            cases = cases[: req.limit]
        with _EVAL_LOCK:
            report = run_suite(card.project, cases, resolve(card.eval.suite), card.eval.thresholds)
        out = report.to_json()
        out["llm_provider"] = os.environ.get("LLM_PROVIDER", "mock")
        return out

    return app
