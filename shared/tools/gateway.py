"""Tool gateway: the one door between agents and MCP systems of record.

Per-agent allowlist (``server.tool`` or ``server.*``), per-tool quotas and a total call
budget, timeouts, per-server circuit breakers, optional retry with backoff for retryable
errors, schema validation of returned payloads (they are *untrusted*), injection
neutralisation of returned strings, typed error re-raising, a call log and OTel spans with
agent + identity. Agents never hold connection strings or god credentials: they hold a
gateway scoped to their identity.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import BaseTool, StructuredTool
from opentelemetry import trace
from pydantic import BaseModel, TypeAdapter, ValidationError

from shared.context.sanitize import sanitize
from shared.observability import telemetry
from shared.resilience import Backoff, CircuitBreaker, CircuitOpenError, retry_call
from shared.tools.connection import McpConnection, error_info, payload


class ToolGatewayError(RuntimeError):
    pass


class ToolDeniedError(ToolGatewayError, PermissionError):
    """Tool not on this agent's allowlist (least privilege)."""


class QuotaExceededError(ToolGatewayError):
    pass


class SchemaViolationError(ToolGatewayError):
    """Returned payload failed validation - treated as a tool failure, never passed on."""


class RemoteToolError(ToolGatewayError):
    def __init__(self, error_type: str, message: str, retryable: bool = False):
        super().__init__(f"{error_type}: {message}")
        self.error_type, self.message, self.retryable = error_type, message, retryable


class SystemOfRecordUnavailableError(ConnectionError):
    """SOR down, timing out or circuit-open. Nodes map this to degrade/escalate exits."""


class ToolTimeoutError(SystemOfRecordUnavailableError, TimeoutError):
    pass


@dataclass
class CallRecord:
    ts: float
    agent: str
    identity: str
    tool: str
    args: dict[str, Any]
    outcome: str  # ok | denied | quota | circuit_open | timeout | error:<type> | schema
    attempts: int = 1
    latency_ms: float = 0.0
    injections: int = 0


def _clean(value: Any) -> tuple[Any, int]:
    """Neutralise injected instructions in every string leaf of an untrusted payload."""
    if isinstance(value, str):
        s = sanitize(value, redact_pii=False)
        return s.text, s.injections
    if isinstance(value, dict):
        out, n = {}, 0
        for k, v in value.items():
            out[k], c = _clean(v)
            n += c
        return out, n
    if isinstance(value, list):
        items = [_clean(v) for v in value]
        return [i for i, _ in items], sum(c for _, c in items)
    return value, 0


@dataclass
class ToolGateway:
    agent: str
    identity: str
    connections: Mapping[str, McpConnection]
    allow: set[str]
    quotas: dict[str, int] = field(default_factory=dict)
    max_calls: int | None = None
    timeout_s: float = 5.0
    schemas: dict[str, Any] = field(default_factory=dict)
    error_types: dict[str, Callable[[str], BaseException]] = field(default_factory=dict)
    retry: Backoff | None = None
    breaker_threshold: int = 3
    breaker_reset_s: float = 30.0
    sanitize_payloads: bool = True
    log: list[CallRecord] = field(default_factory=list)
    breakers: dict[str, CircuitBreaker] = field(default_factory=dict)
    _counts: dict[str, int] = field(default_factory=dict)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # ------------------------------------------------------------------ policy
    def allowed(self, qualified: str) -> bool:
        server = qualified.split(".", 1)[0]
        return qualified in self.allow or f"{server}.*" in self.allow

    def scoped(self, agent: str, identity: str, allow: set[str], **overrides: Any) -> ToolGateway:
        """A narrower gateway (same connections) for another agent / identity."""
        return ToolGateway(
            agent,
            identity,
            self.connections,
            allow,
            schemas=self.schemas,
            error_types=self.error_types,
            timeout_s=self.timeout_s,
            retry=self.retry,
            **overrides,
        )

    def breaker(self, server: str) -> CircuitBreaker:
        if server not in self.breakers:
            self.breakers[server] = CircuitBreaker(
                f"sor:{server}", self.breaker_threshold, self.breaker_reset_s
            )
        return self.breakers[server]

    def _record(self, rec: CallRecord, span: Any) -> None:
        with self._lock:
            self.log.append(rec)
        stats = telemetry().tools
        stats.calls += 1
        stats.by_tool[rec.tool][0] += 1
        if rec.outcome == "denied":
            stats.denied += 1
        elif rec.outcome != "ok":
            stats.errors += 1
            stats.by_tool[rec.tool][1] += 1
        span.set_attribute("tool.outcome", rec.outcome)
        span.set_attribute("tool.attempts", rec.attempts)
        span.set_attribute("tool.latency_ms", round(rec.latency_ms, 2))
        if rec.injections:
            span.set_attribute("tool.injections_neutralised", rec.injections)

    # ------------------------------------------------------------------ call
    def call(self, server: str, tool: str, **args: Any) -> Any:
        qualified = f"{server}.{tool}"
        t = telemetry()
        parent = t.current_parent()
        ctx = trace.set_span_in_context(parent) if parent else None
        with t.tracer.start_as_current_span(
            f"tool {qualified}",
            context=ctx,
            attributes={
                "tool.name": qualified,
                "agent.name": self.agent,
                "enduser.id": self.identity,
                "tool.dry_run": bool(args.get("dry_run", False)),
            },
        ) as span:
            rec = CallRecord(time.time(), self.agent, self.identity, qualified, dict(args), "ok")
            start = time.perf_counter()
            try:
                return self._call(server, tool, qualified, args, rec)
            except Exception as exc:
                span.record_exception(exc)
                raise
            finally:
                rec.latency_ms = (time.perf_counter() - start) * 1000
                self._record(rec, span)

    def _call(
        self, server: str, tool: str, qualified: str, args: dict[str, Any], rec: CallRecord
    ) -> Any:
        if not self.allowed(qualified):
            rec.outcome = "denied"
            raise ToolDeniedError(f"{self.agent} ({self.identity}) may not call {qualified}")
        with self._lock:
            n = self._counts.get(qualified, 0) + 1
            total = sum(self._counts.values()) + 1
            if (qualified in self.quotas and n > self.quotas[qualified]) or (
                self.max_calls is not None and total > self.max_calls
            ):
                rec.outcome = "quota"
                raise QuotaExceededError(f"quota exhausted for {qualified}")
            self._counts[qualified] = n
        br = self.breaker(server)
        if not br.allow():
            rec.outcome = "circuit_open"
            raise SystemOfRecordUnavailableError(f"circuit open for {server}") from (
                CircuitOpenError(server)
            )
        conn = self.connections[server]

        def attempt() -> Any:
            rec.attempts = getattr(attempt, "n", 0) + 1
            attempt.n = rec.attempts  # type: ignore[attr-defined]
            try:
                result = conn.call(tool, args, timeout_s=self.timeout_s)
            except TimeoutError as exc:
                br.failure()
                rec.outcome = "timeout"
                raise ToolTimeoutError(str(exc)) from exc
            if result.isError:
                info = error_info(result)
                etype, msg = info.get("error_type", "ToolError"), info.get("message", "")
                rec.outcome = f"error:{etype}"
                if info.get("retryable"):
                    br.failure()
                    raise SystemOfRecordUnavailableError(f"{qualified}: {msg}")
                br.success()  # business error: the system is healthy
                factory = self.error_types.get(etype)
                raise factory(msg) if factory else RemoteToolError(etype, msg)
            br.success()
            rec.outcome = "ok"
            return payload(result)

        data = (
            retry_call(attempt, backoff=self.retry, retry_on=(SystemOfRecordUnavailableError,))
            if self.retry
            else attempt()
        )
        schema = self.schemas.get(qualified)
        if schema is not None:
            try:
                model = schema if isinstance(schema, TypeAdapter) else TypeAdapter(schema)
                validated = model.validate_python(data)
                data = _dump(validated)
            except ValidationError as exc:
                rec.outcome = "schema"
                raise SchemaViolationError(
                    f"{qualified} returned invalid payload: {exc.errors()[0]['msg']}"
                ) from exc
        if self.sanitize_payloads:
            data, rec.injections = _clean(data)
        return data

    # ------------------------------------------------------------------ LangChain tools
    def langchain_tools(self, names: list[str] | None = None) -> list[BaseTool]:
        """Load allowlisted MCP tools as sync LangChain tools that route via this gateway."""
        out: list[BaseTool] = []
        for server, conn in self.connections.items():
            for t in conn.list_tools():
                q = f"{server}.{t.name}"
                if not self.allowed(q) or (names and t.name not in names and q not in names):
                    continue

                def _fn(_server: str = server, _tool: str = t.name, **kw: Any) -> Any:
                    return self.call(_server, _tool, **kw)

                out.append(
                    StructuredTool.from_function(
                        func=_fn,
                        name=t.name,
                        description=t.description or t.name,
                        args_schema=t.inputSchema,
                    )
                )
        return out

    # ------------------------------------------------------------------ reporting
    def stats(self) -> dict[str, int]:
        return {
            "calls": len(self.log),
            "errors": sum(1 for r in self.log if r.outcome not in ("ok", "denied")),
            "denied": sum(1 for r in self.log if r.outcome == "denied"),
        }

    def last(self, tool: str | None = None) -> CallRecord | None:
        recs = [r for r in self.log if tool is None or r.tool.endswith(tool)]
        return recs[-1] if recs else None


def _dump(v: Any) -> Any:
    if isinstance(v, BaseModel):
        return v.model_dump()
    if isinstance(v, list):
        return [_dump(i) for i in v]
    return v
