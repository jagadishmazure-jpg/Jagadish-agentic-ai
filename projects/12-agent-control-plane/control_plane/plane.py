"""Control plane: who may call whom, per tenant, enforced on every A2A task.

Order of checks in ``authorize`` (first failure wins, every decision is audited):
registration-required (caller and callee) -> kill switch -> prod stage (unless the caller is
a dev agent in a dev tenant) -> tenant entitlement -> allowed callers -> policy rules
(skill + side-effect per tenant) -> budget.
"""

from __future__ import annotations

import threading
from collections import Counter
from dataclasses import dataclass, field

from control_plane.registry import AgentRecord, Registry
from shared.a2a import A2ARejection, AgentCard, CallContext


@dataclass(frozen=True)
class Rule:
    tenant: str  # "*" for any
    caller: str
    callee: str
    skills: frozenset[str]  # skills this caller may use on this callee in this tenant


@dataclass
class ControlPlane:
    registry: Registry
    rules: list[Rule] = field(default_factory=list)
    audit: list[dict[str, str]] = field(default_factory=list)
    _calls: Counter = field(default_factory=Counter)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def allow(self, tenant: str, caller: str, callee: str, *skills: str) -> None:
        self.rules.append(Rule(tenant, caller, callee, frozenset(skills)))

    def _deny(self, ctx: CallContext, callee: str, reason: str, code: int = -32010) -> None:
        self._record(ctx, callee, "deny", reason)
        raise A2ARejection(reason, code)

    def _record(self, ctx: CallContext, callee: str, decision: str, reason: str) -> None:
        with self._lock:
            self.audit.append(
                {
                    "tenant": ctx.tenant or "",
                    "caller": ctx.caller or "",
                    "callee": callee,
                    "skill": ctx.skill,
                    "decision": decision,
                    "reason": reason,
                    "traceparent": ctx.traceparent or "",
                }
            )

    def authorize(self, ctx: CallContext, callee_name: str) -> AgentRecord:
        callee = self.registry.get(callee_name)
        caller = self.registry.get(ctx.caller or "")
        if callee is None:
            self._deny(ctx, callee_name, f"callee {callee_name} is not registered")
        if caller is None:
            self._deny(ctx, callee_name, f"caller {ctx.caller!r} is not registered")
        if not callee.enabled:
            self._deny(
                ctx,
                callee_name,
                f"{callee_name} disabled (kill switch): {callee.kill_reason}",
                -32011,
            )
        if not caller.enabled:
            self._deny(ctx, callee_name, f"caller {caller.name} disabled (kill switch)", -32011)
        if callee.stage != "prod":
            self._deny(ctx, callee_name, f"{callee_name} is not promoted to prod")
        if not ctx.tenant or ctx.tenant not in callee.tenants:
            self._deny(ctx, callee_name, f"tenant {ctx.tenant!r} not entitled to {callee_name}")
        if caller.name not in callee.allowed_callers:
            self._deny(ctx, callee_name, f"{caller.name} is not an allowed caller")
        if ctx.skill not in callee.skills:
            self._deny(ctx, callee_name, f"unknown skill {ctx.skill!r}", -32602)
        if not any(
            r.caller == caller.name
            and r.callee == callee_name
            and ctx.skill in r.skills
            and r.tenant in ("*", ctx.tenant)
            for r in self.rules
        ):
            self._deny(
                ctx,
                callee_name,
                f"policy: {caller.name} may not use "
                f"{callee_name}.{ctx.skill} in tenant {ctx.tenant}",
            )
        key = (caller.name, callee_name, ctx.tenant)
        with self._lock:
            self._calls[key] += 1
            n = self._calls[key]
        if n > callee.budgets.max_calls_per_caller:
            self._deny(ctx, callee_name, f"budget: {n - 1} calls already used", -32012)
        self._record(ctx, callee_name, "allow", callee.skills[ctx.skill])
        return callee

    def guard_for(self, callee_name: str):
        """A2A server guard (``shared.a2a.a2a_app(guard=...)``)."""

        def guard(ctx: CallContext, card: AgentCard) -> None:
            self.authorize(ctx, callee_name)

        return guard
