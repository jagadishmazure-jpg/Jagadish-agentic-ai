"""Resilience primitives: retry with backoff, circuit breaker, model fallback chain, and the
declarative five-exit failure policy every graph node must document.

Doctrine rule: every node has five exits - success, retry (with backoff), compensate a
partial side effect, degrade to a limited but *true* answer, escalate. The fallback chain
never fabricates business state: when every deployment is down it raises
``ModelUnavailableError`` and the calling node takes its degrade exit.
"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, TypeVar

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.outputs import ChatResult
from pydantic import ConfigDict, Field, PrivateAttr

from shared import faults

T = TypeVar("T")
ExitName = Literal["success", "retry", "compensate", "degrade", "escalate"]
EXITS: tuple[str, ...] = ("success", "retry", "compensate", "degrade", "escalate")

# Tests and chaos runs set this to 0 so backoff doesn't slow the suite.
SLEEP_SCALE = 1.0


class ModelUnavailableError(RuntimeError):
    """Every model deployment in the chain failed or is circuit-open."""


class CircuitOpenError(RuntimeError):
    pass


class InjectedFault(ConnectionError):
    """Raised by shared components when a chaos fault is active."""


# --------------------------------------------------------------------------------------
# Retry with exponential backoff + jitter
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Backoff:
    attempts: int = 3
    base_s: float = 0.05
    factor: float = 2.0
    max_s: float = 2.0
    jitter: float = 0.1

    def delays(self) -> Iterator[float]:
        for i in range(self.attempts - 1):
            d = min(self.max_s, self.base_s * self.factor**i)
            yield d * (1 + random.uniform(-self.jitter, self.jitter))


DEFAULT_BACKOFF = Backoff()


def retry_call(
    fn: Callable[[], T],
    *,
    backoff: Backoff | None = None,
    retry_on: tuple[type[BaseException], ...] = (ConnectionError, TimeoutError),
    on_retry: Callable[[int, BaseException], None] | None = None,
) -> T:
    """Call ``fn`` retrying transient errors; re-raises the last error when exhausted."""
    backoff = backoff or DEFAULT_BACKOFF
    delays = list(backoff.delays())
    for attempt in range(backoff.attempts):
        try:
            return fn()
        except retry_on as exc:
            if attempt == backoff.attempts - 1:
                raise
            if on_retry:
                on_retry(attempt + 1, exc)
            time.sleep(delays[attempt] * SLEEP_SCALE)
    raise AssertionError("unreachable")  # pragma: no cover


# --------------------------------------------------------------------------------------
# Circuit breaker
# --------------------------------------------------------------------------------------
@dataclass
class CircuitBreaker:
    name: str
    failure_threshold: int = 3
    reset_after_s: float = 30.0
    clock: Callable[[], float] = time.monotonic
    failures: int = 0
    opened_at: float | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @property
    def state(self) -> str:
        if self.opened_at is None:
            return "closed"
        return "half_open" if self.clock() - self.opened_at >= self.reset_after_s else "open"

    def allow(self) -> bool:
        return self.state != "open"

    def success(self) -> None:
        with self._lock:
            self.failures, self.opened_at = 0, None

    def failure(self) -> None:
        with self._lock:
            self.failures += 1
            if self.failures >= self.failure_threshold or self.opened_at is not None:
                self.opened_at = self.clock()

    def call(self, fn: Callable[[], T]) -> T:
        if not self.allow():
            raise CircuitOpenError(f"circuit '{self.name}' is open")
        try:
            out = fn()
        except Exception:
            self.failure()
            raise
        self.success()
        return out


# --------------------------------------------------------------------------------------
# Model fallback chain
# --------------------------------------------------------------------------------------
class FallbackChatModel(BaseChatModel):
    """primary -> fallback deployment(s) -> ``ModelUnavailableError`` (caller degrades).

    Each member has its own circuit breaker. ``usage`` records which member served each call
    so dashboards can show fallback-model usage.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)
    members: list[BaseChatModel]
    names: list[str] = Field(default_factory=lambda: ["primary", "fallback"])
    failure_threshold: int = 3
    reset_after_s: float = 30.0
    _breakers: dict[str, CircuitBreaker] = PrivateAttr(default_factory=dict)
    _usage: dict[str, int] = PrivateAttr(default_factory=dict)

    @property
    def _llm_type(self) -> str:
        return "fallback-chain"

    def breaker(self, name: str) -> CircuitBreaker:
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(
                f"model:{name}", self.failure_threshold, self.reset_after_s
            )
        return self._breakers[name]

    @property
    def usage(self) -> dict[str, int]:
        return dict(self._usage)

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        errors = []
        for name, model in zip(self.names, self.members, strict=False):
            br = self.breaker(name)
            if not br.allow():
                errors.append(f"{name}: circuit open")
                continue
            try:
                if faults.active("model", f"model:{name}"):
                    raise InjectedFault(f"model:{name} unavailable (injected)")
                result = model._generate(messages, stop=stop, **kwargs)
            except Exception as exc:  # 429 / 5xx / timeout / content-filter
                br.failure()
                errors.append(f"{name}: {type(exc).__name__}: {exc}")
                continue
            br.success()
            self._usage[name] = self._usage.get(name, 0) + 1
            for gen in result.generations:
                gen.message.response_metadata["served_by"] = name
            return result
        raise ModelUnavailableError("all model deployments failed: " + "; ".join(errors))

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> FallbackChatModel:
        bound = [m.bind_tools(tools, **kwargs) for m in self.members]
        clone = self.model_copy(update={"members": bound})
        clone._breakers, clone._usage = self._breakers, self._usage
        return clone


def with_fallback(
    primary: BaseChatModel, fallback: BaseChatModel | None = None, **kwargs: Any
) -> FallbackChatModel:
    """Wrap a model in a fallback chain (idempotent). Without an explicit fallback the same
    model config is reused as the 'fallback deployment' (paired region in production)."""
    if isinstance(primary, FallbackChatModel):
        return primary
    return FallbackChatModel(members=[primary, fallback or primary.model_copy()], **kwargs)


# --------------------------------------------------------------------------------------
# Five-exit policy (declared in doctrine.yaml, rendered into the doctrine card)
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class FiveExitPolicy:
    node: str
    success: str
    retry: str
    compensate: str
    degrade: str
    escalate: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> FiveExitPolicy:
        missing = [k for k in ("node", *EXITS) if not str(d.get(k, "")).strip()]
        if missing:
            raise ValueError(f"five-exit row {d.get('node', '?')} missing: {missing}")
        return cls(**{k: str(d[k]).strip() for k in ("node", *EXITS)})


def exit_table(policies: Sequence[FiveExitPolicy]) -> str:
    head = "| Node | Success | Retry (backoff) | Compensate | Degrade | Escalate |\n"
    head += "|---|---|---|---|---|---|\n"
    rows = [
        f"| `{p.node}` | {p.success} | {p.retry} | {p.compensate} | {p.degrade} | {p.escalate} |"
        for p in policies
    ]
    return head + "\n".join(rows)


def exit_record(node: str, exit: ExitName, reason: str = "") -> dict[str, str]:
    """A state entry recording which exit a node took (graphs keep ``exits`` with add)."""
    assert exit in EXITS, exit
    return {"node": node, "exit": exit, "reason": reason}
