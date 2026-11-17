"""HTTP service for AgentCore Runtime and ECS Fargate.

AgentCore calls ``GET /ping`` and ``POST /invocations`` on port 8080. ``POST /ask`` is the
same handler for a laptop or an ALB. The model stays mock unless ``IT_DESK_PROVIDER=bedrock``.
"""

from __future__ import annotations

import os
import time
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from it_desk.agent import ask
from it_desk.bedrock import resolve_provider
from it_desk.logging import build_sink, event


class AskBody(BaseModel):
    question: str = ""
    prompt: str = ""
    input: dict[str, Any] | None = None


def _question(body: AskBody) -> str:
    if body.question.strip():
        return body.question.strip()
    if body.prompt.strip():
        return body.prompt.strip()
    if body.input:
        for key in ("question", "prompt"):
            value = body.input.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    raise HTTPException(status_code=400, detail="question is required")


def create_app() -> FastAPI:
    app = FastAPI(title="IT desk playbook agent", version="0.1.0")
    sink = build_sink()

    @app.get("/healthz")
    @app.get("/ping")
    def ping() -> dict[str, str]:
        # AgentCore treats status Healthy as a ready runtime. /healthz is the same check.
        return {"status": "Healthy", "provider": resolve_provider()}

    def _handle(body: AskBody) -> dict[str, Any]:
        question = _question(body)
        if len(question) > 2000:
            raise HTTPException(status_code=400, detail="question is too long")
        started = time.perf_counter()
        state = ask(question)
        final = state["final"]
        provider = resolve_provider()
        model = (
            "mock-chat-model" if provider == "mock" else os.getenv("BEDROCK_MODEL_ID", "bedrock")
        )
        record = event(
            provider=provider,
            model=model,
            status=final["status"],
            latency_ms=int((time.perf_counter() - started) * 1000),
            citations=[c["id"] for c in final.get("citations", [])],
            question=question,
        )
        sink.emit(record)
        return {"output": final, "log": record}

    @app.post("/invocations")
    @app.post("/ask")
    def invocations(body: AskBody) -> dict[str, Any]:
        return _handle(body)

    return app
