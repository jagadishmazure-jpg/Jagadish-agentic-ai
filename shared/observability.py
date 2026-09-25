"""OpenTelemetry tracing + cost metering for every graph, model and tool call.

``install()`` registers one LangChain callback handler process-wide (via a configure hook),
so every LangGraph run is traced without touching graph code:

    agent.run <graph>            thread.id, agent, identity
      node <name>                langgraph.node
        llm <model>              gen_ai.usage.input_tokens / output_tokens, cost.usd, served_by
        tool <name>              (LangChain tools)
      tool <server>.<tool>       emitted by the tool gateway: identity, outcome, latency

Exporters: a bounded in-memory exporter (always, used by tests/evals), console when
``OTEL_CONSOLE=1``, OTLP when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is set and
``opentelemetry-exporter-otlp`` is installed (``uv sync --extra otlp``).
"""

from __future__ import annotations

import os
import threading
from collections import defaultdict, deque
from collections.abc import Sequence
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from langchain_core.runnables.config import ensure_config
from langchain_core.tracers.context import register_configure_hook
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.trace import Span, Status, StatusCode

# USD per 1K tokens (input, output). Override with LLM_PRICE_IN_PER_1K / LLM_PRICE_OUT_PER_1K.
DEFAULT_PRICE = (0.00015, 0.0006)  # small-model class pricing, illustrative


class BoundedMemoryExporter(SpanExporter):
    def __init__(self, maxlen: int = 20_000):
        self.spans: deque[ReadableSpan] = deque(maxlen=maxlen)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        self.spans.extend(spans)
        return SpanExportResult.SUCCESS

    def clear(self) -> None:
        self.spans.clear()

    def shutdown(self) -> None:  # pragma: no cover
        pass


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4) if text else 0


@dataclass
class CostMeter:
    price_in: float = float(os.getenv("LLM_PRICE_IN_PER_1K", DEFAULT_PRICE[0]))
    price_out: float = float(os.getenv("LLM_PRICE_OUT_PER_1K", DEFAULT_PRICE[1]))
    tokens_in: int = 0
    tokens_out: int = 0
    usd: float = 0.0
    by_agent: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    by_thread: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def record(self, tin: int, tout: int, agent: str = "", thread: str = "") -> float:
        cost = tin / 1000 * self.price_in + tout / 1000 * self.price_out
        with self._lock:
            self.tokens_in += tin
            self.tokens_out += tout
            self.usd += cost
            self.by_agent[agent] += cost
            self.by_thread[thread] += cost
        return cost

    def snapshot(self) -> dict[str, float]:
        return {"tokens_in": self.tokens_in, "tokens_out": self.tokens_out, "usd": self.usd}


@dataclass
class ToolStats:
    calls: int = 0
    errors: int = 0
    denied: int = 0
    by_tool: dict[str, list[int]] = field(default_factory=lambda: defaultdict(lambda: [0, 0]))

    def snapshot(self) -> dict[str, int]:
        return {"calls": self.calls, "errors": self.errors, "denied": self.denied}


class Telemetry:
    def __init__(self) -> None:
        self.exporter = BoundedMemoryExporter()
        self.provider = TracerProvider(
            resource=Resource.create({"service.name": "agentic-ai-portfolio"})
        )
        self.provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        if os.getenv("OTEL_CONSOLE") == "1":
            self.provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
        if os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
            try:  # optional extra
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                    OTLPSpanExporter,
                )
                from opentelemetry.sdk.trace.export import BatchSpanProcessor

                self.provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
            except ImportError:  # pragma: no cover
                pass
        self.tracer = self.provider.get_tracer("agentic-ai-portfolio")
        self.cost = CostMeter()
        self.tools = ToolStats()
        self.handler = OTelCallbackHandler(self)

    # -- helpers used by the gateway and eval harness ---------------------------------
    def spans(self, name_prefix: str = "") -> list[ReadableSpan]:
        return [s for s in self.exporter.spans if s.name.startswith(name_prefix)]

    def current_parent(self) -> Span | None:
        """Span of the LangChain run currently executing (for gateway tool spans)."""
        try:
            cm = ensure_config().get("callbacks")
        except Exception:  # pragma: no cover
            return None
        run_id = getattr(cm, "parent_run_id", None)
        return self.handler.span_for(run_id) if run_id else None

    def current_run_info(self) -> dict[str, str]:
        parent = self.current_parent()
        if parent is None:
            return {}
        return self.handler.info_for_span(parent)


class OTelCallbackHandler(BaseCallbackHandler):
    """Maps LangChain/LangGraph run events to OTel spans (graph, node, llm, tool)."""

    raise_error = False

    def __init__(self, telemetry: Telemetry):
        self.t = telemetry
        self._spans: dict[UUID, Span] = {}
        self._owned: set[UUID] = set()
        self._info: dict[int, dict[str, str]] = {}
        self._prompt_chars: dict[UUID, int] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ bookkeeping
    def span_for(self, run_id: UUID | None) -> Span | None:
        return self._spans.get(run_id) if run_id else None

    def info_for_span(self, span: Span) -> dict[str, str]:
        return self._info.get(id(span), {})

    def _start(
        self,
        run_id: UUID,
        parent_run_id: UUID | None,
        name: str,
        attrs: dict[str, Any],
        info: dict[str, str] | None = None,
    ) -> None:
        parent = self.span_for(parent_run_id)
        ctx = trace.set_span_in_context(parent) if parent else None
        span = self.t.tracer.start_span(
            name, context=ctx, attributes={k: v for k, v in attrs.items() if v}
        )
        base = self._info.get(id(parent), {}) if parent else {}
        with self._lock:
            self._spans[run_id] = span
            self._owned.add(run_id)
            self._info[id(span)] = {**base, **(info or {})}

    def _passthrough(self, run_id: UUID, parent_run_id: UUID | None) -> None:
        parent = self.span_for(parent_run_id)
        if parent is not None:
            with self._lock:
                self._spans[run_id] = parent

    def _end(self, run_id: UUID, error: BaseException | None = None) -> None:
        with self._lock:
            span = self._spans.pop(run_id, None)
            owned = run_id in self._owned
            self._owned.discard(run_id)
            if span is not None and owned:
                self._info.pop(id(span), None)
        if span is not None and owned:
            if error is not None:
                span.record_exception(error)
                span.set_status(Status(StatusCode.ERROR, type(error).__name__))
            span.end()

    # ------------------------------------------------------------------ chains / nodes
    def on_chain_start(
        self,
        serialized: dict[str, Any] | None,
        inputs: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        metadata: dict | None = None,
        **kwargs: Any,
    ) -> None:
        md = metadata or {}
        name = kwargs.get("name") or (serialized or {}).get("name", "chain")
        if parent_run_id is None:
            thread = str(md.get("thread_id", ""))
            identity = str(md.get("identity", "") or md.get("agent_identity", ""))
            self._start(
                run_id,
                None,
                f"agent.run {name}",
                {"agent.name": name, "thread.id": thread, "enduser.id": identity},
                {"agent": name, "thread": thread, "identity": identity},
            )
        elif md.get("langgraph_node") == name and parent_run_id in self._owned:
            self._start(
                run_id, parent_run_id, f"node {name}", {"langgraph.node": name}, {"node": name}
            )
        else:
            self._passthrough(run_id, parent_run_id)

    def on_chain_end(self, outputs: Any, *, run_id: UUID, **kwargs: Any) -> None:
        self._end(run_id)

    def on_chain_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        # GraphInterrupt is control flow (HITL), not an error.
        self._end(run_id, None if type(error).__name__ == "GraphInterrupt" else error)

    # ------------------------------------------------------------------ models
    def on_chat_model_start(
        self,
        serialized: dict[str, Any] | None,
        messages: list[list[Any]],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        chars = sum(len(str(m.content)) for batch in messages for m in batch)
        name = kwargs.get("name") or (serialized or {}).get("name", "chat_model")
        self._prompt_chars[run_id] = chars
        self._start(run_id, parent_run_id, f"llm {name}", {"gen_ai.request.model": name})

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        span = self._spans.get(run_id)
        tin = estimate_tokens("x" * self._prompt_chars.pop(run_id, 0))
        tout, served = 0, ""
        for gens in response.generations:
            for g in gens:
                msg = getattr(g, "message", None)
                usage = getattr(msg, "usage_metadata", None) or {}
                if usage:
                    tin = usage.get("input_tokens", tin)
                    tout += usage.get("output_tokens", 0)
                else:
                    tout += estimate_tokens(str(getattr(msg, "content", g.text)))
                served = (getattr(msg, "response_metadata", None) or {}).get("served_by", served)
        info = self.info_for_span(span) if span else {}
        cost = self.t.cost.record(tin, tout, info.get("agent", ""), info.get("thread", ""))
        if span is not None:
            span.set_attribute("gen_ai.usage.input_tokens", tin)
            span.set_attribute("gen_ai.usage.output_tokens", tout)
            span.set_attribute("cost.usd", round(cost, 8))
            if served:
                span.set_attribute("gen_ai.served_by", served)
        self._end(run_id)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._prompt_chars.pop(run_id, None)
        self._end(run_id, error)

    # ------------------------------------------------------------------ LangChain tools
    def on_tool_start(
        self,
        serialized: dict[str, Any] | None,
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        name = kwargs.get("name") or (serialized or {}).get("name", "tool")
        self._start(run_id, parent_run_id, f"tool {name}", {"tool.name": name})

    def on_tool_end(self, output: Any, *, run_id: UUID, **kwargs: Any) -> None:
        self._end(run_id)

    def on_tool_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        self._end(run_id, error)


_telemetry: Telemetry | None = None
_handler_var: ContextVar[BaseCallbackHandler | None] = ContextVar("otel_handler", default=None)
_install_lock = threading.Lock()


def install() -> Telemetry:
    """Idempotently enable process-wide tracing; returns the Telemetry singleton."""
    global _telemetry
    with _install_lock:
        if _telemetry is None:
            _telemetry = Telemetry()
            register_configure_hook(_handler_var, inheritable=True)
        # the handler lives in a ContextVar: set it in this context too, so a first install()
        # from a worker thread (e.g. an ASGI test portal) does not leave the caller untraced
        if _handler_var.get() is None:
            _handler_var.set(_telemetry.handler)
    return _telemetry


def telemetry() -> Telemetry:
    return install()


def run_config(thread_id: str, identity: str = "", **configurable: Any) -> dict[str, Any]:
    """Standard invoke config: thread id + identity propagate into span attributes."""
    return {
        "configurable": {"thread_id": thread_id, **configurable},
        "metadata": {"identity": identity},
    }
