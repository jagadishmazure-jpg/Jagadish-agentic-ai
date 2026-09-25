"""A2A caller: fetch agent cards, send tasks with traceparent + tenant propagation."""

from __future__ import annotations

import itertools
from typing import Any

import httpx
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from shared import faults
from shared.a2a.models import AgentCard, DataPart, Message, Task
from shared.observability import telemetry

_ids = itertools.count(1)


class A2AError(RuntimeError):
    def __init__(self, code: int, message: str):
        super().__init__(f"[{code}] {message}")
        self.code, self.reason = code, message


class A2AUnavailableError(ConnectionError):
    """Peer agent unreachable / unavailable: callers take their degrade exit."""


class A2AClient:
    """``http`` is any httpx-style client: ``httpx.Client(base_url=...)`` in production,
    ``fastapi.testclient.TestClient(app)`` in-process for tests and demos. Timeouts belong on
    the httpx client (``httpx.Client(timeout=5.0)``)."""

    def __init__(self, name: str, http: httpx.Client, caller: str):
        self.name, self.http, self.caller = name, http, caller

    def card(self) -> AgentCard:
        return AgentCard.model_validate(self.http.get("/.well-known/agent.json").json())

    def send(self, skill: str, data: dict[str, Any], *, tenant: str) -> Task:
        t = telemetry()
        with t.tracer.start_as_current_span(
            f"a2a.client {self.name}/{skill}",
            attributes={
                "a2a.agent": self.name,
                "a2a.skill": skill,
                "tenant.id": tenant,
                "a2a.caller": self.caller,
            },
        ) as span:
            headers: dict[str, str] = {"x-tenant-id": tenant, "x-caller-agent": self.caller}
            TraceContextTextMapPropagator().inject(headers)
            msg = Message(parts=[DataPart(data=data)], metadata={"skill": skill})
            body = {
                "jsonrpc": "2.0",
                "id": next(_ids),
                "method": "message/send",
                "params": {"message": msg.model_dump()},
            }
            if faults.active(*faults.scopes("a2a", self.name)):
                raise A2AUnavailableError(f"{self.name} unreachable (injected)")
            try:
                resp = self.http.post("/", json=body, headers=headers)
            except (httpx.TransportError, OSError) as exc:
                raise A2AUnavailableError(f"{self.name} unreachable: {exc}") from exc
            if resp.status_code >= 500:
                raise A2AUnavailableError(f"{self.name} HTTP {resp.status_code}")
            out = resp.json()
            if "error" in out:
                code, message = out["error"]["code"], out["error"]["message"]
                span.set_attribute("a2a.error", message)
                if code == -32004:
                    raise A2AUnavailableError(f"{self.name}: {message}")
                raise A2AError(code, message)
            task = Task.model_validate(out["result"])
            span.set_attribute("a2a.task_state", task.status.state)
            return task
