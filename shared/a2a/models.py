"""Pydantic models for the A2A task contract (subset of the public protocol shape)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field

TaskState = Literal[
    "submitted", "working", "input-required", "completed", "canceled", "failed", "rejected"
]


def _id() -> str:
    return uuid.uuid4().hex


class TextPart(BaseModel):
    kind: Literal["text"] = "text"
    text: str


class DataPart(BaseModel):
    kind: Literal["data"] = "data"
    data: dict[str, Any]


Part = Annotated[TextPart | DataPart, Field(discriminator="kind")]


class Message(BaseModel):
    kind: Literal["message"] = "message"
    role: Literal["user", "agent"] = "user"
    messageId: str = Field(default_factory=_id)
    parts: list[Part]
    contextId: str | None = None
    taskId: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    def data(self) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for p in self.parts:
            if isinstance(p, DataPart):
                merged.update(p.data)
        return merged

    def text(self) -> str:
        return "\n".join(p.text for p in self.parts if isinstance(p, TextPart))


class TaskStatus(BaseModel):
    state: TaskState
    message: str = ""
    timestamp: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class Artifact(BaseModel):
    artifactId: str = Field(default_factory=_id)
    name: str
    parts: list[Part]

    def data(self) -> dict[str, Any]:
        return next((p.data for p in self.parts if isinstance(p, DataPart)), {})


class Task(BaseModel):
    kind: Literal["task"] = "task"
    id: str = Field(default_factory=_id)
    contextId: str = Field(default_factory=_id)
    status: TaskStatus
    artifacts: list[Artifact] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def artifact(self, name: str) -> dict[str, Any]:
        return next((a.data() for a in self.artifacts if a.name == name), {})


class AgentSkill(BaseModel):
    id: str
    name: str
    description: str
    tags: list[str] = Field(default_factory=list)
    inputSchema: dict[str, Any] = Field(default_factory=dict)


class AgentCapabilities(BaseModel):
    streaming: bool = False
    pushNotifications: bool = False


class AgentCard(BaseModel):
    """Public agent card + control-plane metadata (owner, side effects, budgets, evals)."""

    name: str
    description: str
    url: str
    version: str = "1.0.0"
    protocolVersion: str = "0.3.0"
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    defaultInputModes: list[str] = Field(default_factory=lambda: ["application/json"])
    defaultOutputModes: list[str] = Field(default_factory=lambda: ["application/json"])
    skills: list[AgentSkill]
    metadata: dict[str, Any] = Field(default_factory=dict)


class CallContext(BaseModel):
    """Who is calling, for which tenant, inside which trace (from request headers)."""

    tenant: str | None = None
    caller: str | None = None
    traceparent: str | None = None
    skill: str = ""
