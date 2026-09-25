"""FastAPI server for one agent: agent card + JSON-RPC ``message/send`` / ``tasks/get``."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from pydantic import BaseModel, ValidationError

from shared import faults
from shared.a2a.models import AgentCard, Artifact, CallContext, DataPart, Message, Task, TaskStatus
from shared.observability import telemetry

# JSON-RPC error codes (standard + A2A-style application codes)
INVALID_REQUEST, METHOD_NOT_FOUND, INVALID_PARAMS = -32600, -32601, -32602
TASK_NOT_FOUND, UNAVAILABLE, REJECTED = -32001, -32004, -32010


class A2ARejection(Exception):
    """Raised by a guard (policy engine, kill switch, registry gate) to refuse a task."""

    def __init__(self, reason: str, code: int = REJECTED):
        super().__init__(reason)
        self.code = code


@dataclass
class Skill:
    input_model: type[BaseModel]
    handler: Callable[[BaseModel, CallContext], dict[str, Any]]
    artifact: str = "result"


Guard = Callable[[CallContext, AgentCard], None]


def _err(rid: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def a2a_app(card: AgentCard, skills: dict[str, Skill], guard: Guard | None = None) -> FastAPI:
    """One agent = one app. ``guard`` runs before schema validation and the handler."""
    app = FastAPI(title=card.name)
    tasks: dict[str, Task] = {}
    for s in card.skills:
        if s.id in skills and not s.inputSchema:
            s.inputSchema = skills[s.id].input_model.model_json_schema()

    @app.get("/.well-known/agent.json")
    def agent_card() -> dict[str, Any]:
        return card.model_dump()

    @app.post("/")
    async def rpc(request: Request) -> dict[str, Any]:
        try:
            body = await request.json()
        except ValueError:
            return _err(None, INVALID_REQUEST, "body is not JSON")
        rid = body.get("id") if isinstance(body, dict) else None
        if not isinstance(body, dict) or body.get("jsonrpc") != "2.0" or "method" not in body:
            return _err(rid, INVALID_REQUEST, "not a JSON-RPC 2.0 request")
        params = body.get("params") or {}
        if body["method"] == "tasks/get":
            t = tasks.get(str(params.get("id")))
            return (
                {"jsonrpc": "2.0", "id": rid, "result": t.model_dump()}
                if t
                else _err(rid, TASK_NOT_FOUND, "task not found")
            )
        if body["method"] != "message/send":
            return _err(rid, METHOD_NOT_FOUND, f"unknown method {body['method']}")
        try:
            msg = Message.model_validate(params.get("message"))
        except ValidationError as exc:
            return _err(rid, INVALID_PARAMS, f"invalid message: {exc.errors()[0]['msg']}")
        ctx = CallContext(
            tenant=request.headers.get("x-tenant-id"),
            caller=request.headers.get("x-caller-agent"),
            traceparent=request.headers.get("traceparent"),
            skill=str(msg.metadata.get("skill", "")),
        )
        parent = TraceContextTextMapPropagator().extract(dict(request.headers))
        with telemetry().tracer.start_as_current_span(
            f"a2a.server {card.name}/{ctx.skill}",
            context=parent,
            attributes={
                "a2a.agent": card.name,
                "a2a.skill": ctx.skill,
                "tenant.id": ctx.tenant or "",
                "a2a.caller": ctx.caller or "",
            },
        ) as span:
            if faults.active(*faults.scopes("a2a", card.name)):
                return _err(rid, UNAVAILABLE, f"{card.name} unavailable (injected)")
            try:
                if guard:
                    guard(ctx, card)
                if ctx.skill not in skills:
                    raise A2ARejection(f"unknown skill '{ctx.skill}'", INVALID_PARAMS)
                skill = skills[ctx.skill]
                try:
                    inp = skill.input_model.model_validate(msg.data())
                except ValidationError as exc:
                    e = exc.errors()[0]
                    raise A2ARejection(
                        f"schema rejected: {'.'.join(map(str, e['loc']))}: {e['msg']}",
                        INVALID_PARAMS,
                    ) from exc
            except A2ARejection as rej:
                span.set_attribute("a2a.rejected", str(rej))
                return _err(rid, rej.code, str(rej))
            try:
                out = skill.handler(inp, ctx)
                status = TaskStatus(state="completed")
            except Exception as exc:  # agent failure -> failed task, never a 500
                out, status = (
                    {"error": f"{type(exc).__name__}: {exc}"},
                    TaskStatus(state="failed", message=str(exc)),
                )
            task = Task(
                contextId=msg.contextId or msg.messageId,
                status=status,
                artifacts=[Artifact(name=skill.artifact, parts=[DataPart(data=out)])],
                metadata={"tenant": ctx.tenant, "traceparent": ctx.traceparent},
            )
            tasks[task.id] = task
            span.set_attribute("a2a.task_state", status.state)
            return {"jsonrpc": "2.0", "id": rid, "result": task.model_dump()}

    return app
