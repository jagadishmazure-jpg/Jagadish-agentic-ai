"""Common harness every pattern runs inside.

* **Budgets**: max agent turns, max LLM calls, max tokens. ``guard()`` returns a stop reason.
* **Metering**: LLM calls, estimated tokens, tool calls and a *simulated* latency per turn
  (constants below). Parallel branches share a start clock and ``clock_ms`` keeps the max, so a
  run reports its critical path, not the sum of all work.
* **Loop / ping-pong detection** over the turn history, plus a no-progress check.
* **Route validation**: every proposed handoff / route / speaker is checked against the agent
  registry, so a bad handoff never reaches an unknown or unauthorised agent.
* **Fault plan** for the comparison runner: one worker down, a looping reviewer, a bad handoff.
* **Tracing**: one OpenTelemetry span per agent turn (``agent <name>``) under the LangGraph node
  span, with pattern, tokens, LLM calls and simulated latency as attributes.
* **Termination**: ``finish()`` turns a workspace into a result with an explicit stop reason and
  records the five-exit outcome for the pattern node.

The human-in-the-loop hook lives in the arena graph (``graph.py``): a referral pauses at
``interrupt()`` whichever pattern produced it.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from orchestration_lab import knowledge, mock_llm, routing
from orchestration_lab.prompts import SYSTEM
from orchestration_lab.sor import LoanSystems, gateways
from shared.observability import estimate_tokens, install, telemetry
from shared.resilience import ModelUnavailableError, exit_record, with_fallback

# Simulated latency model (documented in the README; not a measurement of any real service).
LLM_BASE_MS = 350.0  # time to first token
LLM_MS_PER_IN_TOKEN = 0.05  # prompt processing
LLM_MS_PER_OUT_TOKEN = 12.0  # ~80 output tokens / second
TOOL_MS = 150.0  # one MCP call to a system of record
RETRIEVAL_MS = 200.0  # one context-builder query
CODE_MS = 20.0  # deterministic step (reviewer checks, blackboard control)
TIMEOUT_MS = 1500.0  # a worker that is down costs a timeout before the caller sees it

REGISTRY = frozenset(
    {*routing.WORKERS, "advocate", "risk_officer", "supervisor", "moderator", "manager"}
)
BOGUS_TARGET = "funds_disbursement_agent"  # what the bad-handoff fault proposes


class AgentUnavailableError(ConnectionError):
    """The worker is down (fault plan)."""


class MissingInputError(RuntimeError):
    """An agent was asked to act before its prerequisites were in the workspace."""


@dataclass(frozen=True)
class Budgets:
    max_turns: int = 30
    max_llm_calls: int = 40
    max_tokens: int = 40_000


@dataclass(frozen=True)
class FaultPlan:
    down: str | None = None  # agent that always fails
    loop: bool = False  # reviewer never satisfied (same issue every time)
    bad_handoff: bool = False  # the first route decision names an unregistered agent

    @property
    def label(self) -> str:
        if self.down:
            return f"{self.down}_down"
        if self.loop:
            return "looping_reviewer"
        return "bad_handoff" if self.bad_handoff else "none"


@dataclass
class Meter:
    """Per-turn accounting."""

    llm_calls: int = 0
    tokens: int = 0
    tool_calls: int = 0
    ms: float = 0.0
    degraded: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)  # merged into every payload (group chat)

    def llm(self, tin: int, tout: int) -> None:
        self.llm_calls += 1
        self.tokens += tin + tout
        self.ms += LLM_BASE_MS + LLM_MS_PER_IN_TOKEN * tin + LLM_MS_PER_OUT_TOKEN * tout


class Harness:
    def __init__(
        self,
        pattern: str,
        *,
        systems: LoanSystems | None = None,
        llm: BaseChatModel | None = None,
        budgets: Budgets | None = None,
        faults: FaultPlan | None = None,
        run_id: str | None = None,
    ):
        install()
        self.pattern = pattern
        self.systems = systems or LoanSystems()
        self.gw = gateways(self.systems)
        self.ctx = knowledge.builder()
        if llm is None:
            from shared.llm import get_llm

            llm = get_llm(mock_responder=mock_llm.respond)
        self.llm = with_fallback(llm)
        self.budgets = budgets or Budgets()
        self.faults = faults or FaultPlan()
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self._bad_handoffs_left = 1 if self.faults.bad_handoff else 0

    # ------------------------------------------------------------------ model / tools
    def ask(self, role: str, payload: dict[str, Any], m: Meter) -> dict[str, Any] | None:
        """One model call. Returns parsed JSON, or None (model down / unparseable) so the caller
        takes its deterministic fallback."""
        system = SYSTEM[role]
        human = json.dumps({**payload, **m.extra}, sort_keys=True, default=str)
        try:
            msg = self.llm.invoke([SystemMessage(system), HumanMessage(human)])
        except ModelUnavailableError:
            m.degraded.append(f"{role}: model unavailable")
            return None
        text = str(msg.content)
        m.llm(estimate_tokens(system + human), estimate_tokens(text))
        try:
            out = json.loads(text)
        except json.JSONDecodeError:
            m.degraded.append(f"{role}: unparseable output")
            return None
        return out if isinstance(out, dict) else None

    def tool(self, gw: str, server: str, tool: str, m: Meter, **args: Any) -> Any:
        m.tool_calls += 1
        m.ms += TOOL_MS
        return self.gw[gw].call(server, tool, **args)

    def retrieve(self, query: str, as_of: Any, m: Meter, k: int = 3):
        m.ms += RETRIEVAL_MS
        return self.ctx.build(query, knowledge.principal(), as_of=as_of, k=k)

    # ------------------------------------------------------------------ one agent turn
    def turn(
        self,
        agent: str,
        state: dict[str, Any],
        fn: Callable[..., tuple[dict[str, Any], dict[str, Any]]],
        *,
        extra: dict[str, Any] | None = None,
        label: str | None = None,
        **kw: Any,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Run ``fn(harness, state, meter, **kw) -> (ws_update, info)`` as one metered, traced
        turn. Returns the state update and the agent's info (route proposals etc.)."""
        m = Meter(extra=dict(extra or {}))
        start = float(state.get("clock_ms") or 0.0)
        name = label or agent
        t = telemetry()
        parent = t.current_parent()
        from opentelemetry import trace

        ctx = trace.set_span_in_context(parent) if parent else None
        ws_update: dict[str, Any] = {}
        info: dict[str, Any] = {}
        error = ""
        with t.tracer.start_as_current_span(f"agent {name}", context=ctx) as span:
            try:
                if self.faults.down == agent:
                    m.ms += TIMEOUT_MS
                    raise AgentUnavailableError(f"{agent} unavailable (timeout)")
                ws_update, info = fn(self, state, m, **kw)
            except Exception as exc:  # the pattern decides what a failed turn means
                error = f"{type(exc).__name__}: {exc}"
                ws_update = {"errors": {agent: error}}
                span.record_exception(exc)
            span.set_attributes(
                {
                    "orchestration.pattern": self.pattern,
                    "orchestration.run_id": self.run_id,
                    "agent.name": name,
                    "agent.ok": not error,
                    "llm.calls": m.llm_calls,
                    "gen_ai.usage.total_tokens": m.tokens,
                    "tool.calls": m.tool_calls,
                    "sim.latency_ms": round(m.ms, 1),
                }
            )
        rec = {
            "agent": name,
            "ok": not error,
            "error": error,
            "llm_calls": m.llm_calls,
            "tokens": m.tokens,
            "tool_calls": m.tool_calls,
            "start_ms": round(start, 1),
            "ms": round(m.ms, 1),
            "note": info.get("note", ""),
        }
        update: dict[str, Any] = {
            "ws": ws_update,
            "turns": [rec],
            "clock_ms": start + m.ms,
            "llm_calls": m.llm_calls,
            "tokens": m.tokens,
            "tool_calls": m.tool_calls,
            "exits": [
                exit_record(self.pattern, "degrade", f"{name}: {d}; deterministic fallback")
                for d in m.degraded
            ]
            + list(info.get("exits", [])),
        }
        return update, {**info, "ok": not error, "error": error}

    def code_step(self, state: dict[str, Any], name: str, ms: float = CODE_MS) -> dict[str, Any]:
        """A deterministic control step (no model): costs a little simulated time only."""
        return {"clock_ms": float(state.get("clock_ms") or 0.0) + ms}

    # ------------------------------------------------------------------ guards
    def guard(self, state: dict[str, Any]) -> str | None:
        b = self.budgets
        if len(state.get("turns", [])) >= b.max_turns:
            return "budget_exhausted:turns"
        if state.get("llm_calls", 0) >= b.max_llm_calls:
            return "budget_exhausted:llm_calls"
        if state.get("tokens", 0) >= b.max_tokens:
            return "budget_exhausted:tokens"
        return None

    def propose(self, target: Any) -> str:
        """Pass a model-proposed target through the fault plan (bad handoff fires once)."""
        if self._bad_handoffs_left and isinstance(target, str) and target not in ("FINISH", "END"):
            self._bad_handoffs_left -= 1
            return BOGUS_TARGET
        return str(target) if target is not None else ""

    @staticmethod
    def valid_target(target: str, allowed: set[str] | frozenset[str]) -> bool:
        return target in allowed and (target in REGISTRY or target in ("FINISH", "END", "DONE"))

    @staticmethod
    def ping_pong(turns: list[dict[str, Any]], cycles: int = 3) -> bool:
        """A-B-A-B-A-B over the last 2*cycles turns."""
        names = [t["agent"] for t in turns][-2 * cycles :]
        if len(names) < 2 * cycles:
            return False
        a, b = names[0], names[1]
        return a != b and all(n == (a if i % 2 == 0 else b) for i, n in enumerate(names))

    @staticmethod
    def repeated_review(ws: dict[str, Any], history: list[list[str]]) -> bool:
        """The same review issues came back again: the loop is not making progress."""
        r = ws.get("review")
        return bool(r and not r["passed"] and history.count(list(r["issues"])) >= 2)

    # ------------------------------------------------------------------ termination
    def finish(self, state: dict[str, Any], stop: str | None = None) -> dict[str, Any]:
        """Final result for the pattern. A passed review is the only 'completed' path; anything
        else is a referral to a human with the stop reason (never a guessed decision)."""
        ws = state.get("ws", {})
        draft, review = ws.get("draft"), ws.get("review")
        if stop is None and draft and review and review["passed"] and routing.reviewed_current(ws):
            result = {
                "decision": draft["decision"],
                "conditions": list(draft["conditions"]),
                "citations": list(draft["citations"]),
                "memo": draft["memo"],
                "stop_reason": "completed",
            }
            return {"result": result, **self.code_step(state, "finish")}
        reason = stop or self._why(ws)
        result = {
            "decision": "escalate",
            "conditions": [],
            "citations": [],
            "memo": "",
            "stop_reason": reason,
        }
        return {
            "result": result,
            "exits": [exit_record(self.pattern, "escalate", reason)],
            **self.code_step(state, "finish"),
        }

    @staticmethod
    def _why(ws: dict[str, Any]) -> str:
        if failed := routing.failed(ws):
            return f"worker_failed:{failed[0]}"
        if ws.get("review") and not ws["review"]["passed"]:
            return "review_failed"
        return "incomplete"
