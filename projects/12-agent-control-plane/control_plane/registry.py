"""Agent registry: every agent has a card (purpose, skills, tools, models, budgets, owner,
allowed callers, side-effect class, eval scores). Unregistered agents cannot call or be
called; promotion to ``prod`` is gated on eval scores per side-effect class."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

SideEffect = Literal["read_only", "reversible_write", "irreversible_write"]
Stage = Literal["dev", "prod"]

# promotion gate: stricter bars for agents that change state
PROMOTION_BARS: dict[str, dict[str, float]] = {
    "read_only": {"task_success": 0.80, "policy_violation_rate": 0.0},
    "reversible_write": {"task_success": 0.90, "policy_violation_rate": 0.0},
    "irreversible_write": {"task_success": 0.95, "policy_violation_rate": 0.0},
}


class Budgets(BaseModel):
    max_calls_per_caller: int = Field(100, ge=1)  # per caller + tenant (sliding window in prod)
    max_tokens_per_task: int = Field(4000, ge=1)
    max_cost_usd_per_task: float = Field(0.05, gt=0)


class AgentRecord(BaseModel):
    name: str = Field(pattern=r"^[a-z][a-z0-9-]+$")
    version: str
    purpose: str = Field(min_length=10)
    owner: str
    skills: dict[str, SideEffect]  # skill id -> side-effect class
    tools: list[str] = Field(default_factory=list)  # MCP tools the agent itself uses
    models: list[str] = Field(default_factory=list)  # primary + fallback deployments
    budgets: Budgets = Field(default_factory=Budgets)
    allowed_callers: list[str] = Field(default_factory=list)
    tenants: list[str] = Field(min_length=1)
    eval_scores: dict[str, float] = Field(default_factory=dict)
    stage: Stage = "dev"
    enabled: bool = True
    kill_reason: str = ""

    @property
    def side_effect(self) -> SideEffect:
        order = ["read_only", "reversible_write", "irreversible_write"]
        return max(self.skills.values(), key=order.index)


class RegistryError(ValueError):
    pass


class Registry:
    def __init__(self) -> None:
        self._agents: dict[str, AgentRecord] = {}
        self.events: list[dict[str, str]] = []

    def _log(self, event: str, name: str, detail: str = "") -> None:
        self.events.append(
            {"at": datetime.now(UTC).isoformat(), "event": event, "agent": name, "detail": detail}
        )

    def register(self, record: AgentRecord) -> AgentRecord:
        if record.stage != "dev":
            raise RegistryError("new registrations start in dev; use promote()")
        self._agents[record.name] = record
        self._log("registered", record.name, record.version)
        return record

    def get(self, name: str) -> AgentRecord | None:
        return self._agents.get(name)

    def all(self) -> list[AgentRecord]:
        return list(self._agents.values())

    def gate(self, name: str) -> list[str]:
        """Promotion problems for an agent (empty == promotable)."""
        rec = self._agents[name]
        bars = PROMOTION_BARS[rec.side_effect]
        problems = []
        for metric, bar in bars.items():
            score = rec.eval_scores.get(metric)
            if score is None:
                problems.append(f"no {metric} score")
            elif (metric.endswith("_rate") and score > bar) or (
                not metric.endswith("_rate") and score < bar
            ):
                problems.append(f"{metric}={score} misses {rec.side_effect} bar {bar}")
        return problems

    def promote(self, name: str) -> AgentRecord:
        problems = self.gate(name)
        if problems:
            self._log("promotion_refused", name, "; ".join(problems))
            raise RegistryError(f"{name} not promotable: {'; '.join(problems)}")
        rec = self._agents[name] = self._agents[name].model_copy(update={"stage": "prod"})
        self._log("promoted", name)
        return rec

    def kill(self, name: str, reason: str) -> None:
        self._agents[name] = self._agents[name].model_copy(
            update={"enabled": False, "kill_reason": reason}
        )
        self._log("killed", name, reason)

    def revive(self, name: str) -> None:
        self._agents[name] = self._agents[name].model_copy(
            update={"enabled": True, "kill_reason": ""}
        )
        self._log("revived", name)
