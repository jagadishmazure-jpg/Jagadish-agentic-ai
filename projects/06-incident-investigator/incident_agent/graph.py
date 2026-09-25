"""Outer graph: open_case -> investigator (create_agent ReAct loop + guardrail middleware,
propose_rollback interrupts for approval) -> write_report (schema + evidence validation)."""

from __future__ import annotations

import json
import re
from typing import Annotated, Any, Literal, TypedDict

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from pydantic import BaseModel, Field, ValidationError

from incident_agent.guards import STOP_PREFIX, GuardrailMiddleware, spent
from incident_agent.llm import SYSTEM, mock_investigator
from incident_agent.systems import Systems
from incident_agent.tools import make_tools

MIN_EVIDENCE = 2


class ReportDraft(BaseModel):
    root_cause: str
    summary: str
    confidence: float = Field(ge=0, le=1)
    evidence: list[str]
    timeline: list[str] = Field(default_factory=list)
    mitigation: str


class RootCauseReport(BaseModel):
    service: str
    status: Literal["mitigated", "mitigation_rejected", "diagnosed", "needs_human", "incomplete"]
    root_cause: str | None = None
    summary: str
    confidence: float = 0.0
    evidence: list[str] = Field(default_factory=list)
    timeline: list[str] = Field(default_factory=list)
    mitigation: str | None = None
    stop_reason: str | None = None
    problems: list[str] = Field(default_factory=list)
    tools_called: list[str] = Field(default_factory=list)
    tool_cost: int = 0


class IncidentState(TypedDict, total=False):
    alert: dict[str, Any]
    messages: Annotated[list[AnyMessage], add_messages]
    report: dict[str, Any]


def build_graph(
    systems: Systems,
    llm: BaseChatModel | None = None,
    checkpointer: BaseCheckpointSaver | None = None,
    *,
    max_steps: int = 8,
    max_tool_cost: int = 20,
):
    if llm is None:
        from shared.llm import get_llm

        llm = get_llm(mock_responder=mock_investigator)
    investigator = create_agent(
        llm,
        make_tools(systems),
        system_prompt=SYSTEM,
        name="investigator",
        middleware=[GuardrailMiddleware(max_steps=max_steps, max_tool_cost=max_tool_cost)],
    )

    def open_case(state: IncidentState) -> dict[str, Any]:
        return {"messages": [HumanMessage(json.dumps(state["alert"]))]}

    def write_report(state: IncidentState) -> dict[str, Any]:
        msgs = state["messages"]
        tool_msgs = [m for m in msgs if isinstance(m, ToolMessage)]
        observed = {m.artifact["evidence_id"] for m in tool_msgs if isinstance(m.artifact, dict)}
        base = {
            "service": state["alert"]["service"],
            "tools_called": [m.name for m in tool_msgs],
            "tool_cost": spent(msgs),
        }
        final = str(next(m for m in reversed(msgs) if isinstance(m, AIMessage)).content)
        if final.startswith(STOP_PREFIX):
            report = RootCauseReport(
                **base,
                status="incomplete",
                stop_reason=final[len(STOP_PREFIX) :].strip(),
                evidence=sorted(observed),
                summary="Investigation stopped by guardrail; escalating to on-call with the "
                "evidence gathered so far.",
            )
            return {"report": report.model_dump()}
        try:
            m = re.search(r"\{.*\}", final, re.S)
            draft = ReportDraft.model_validate_json(m.group(0) if m else final)
        except ValidationError as e:
            report = RootCauseReport(
                **base,
                status="needs_human",
                summary="Unparseable report",
                problems=[str(e.errors()[0]["msg"])],
            )
            return {"report": report.model_dump()}
        problems = [
            f"cited evidence {e} was never observed" for e in draft.evidence if e not in observed
        ]
        if len(set(draft.evidence) & observed) < MIN_EVIDENCE:
            problems.append(f"fewer than {MIN_EVIDENCE} valid evidence citations")
        rollback = next((m for m in tool_msgs if m.name == "propose_rollback"), None)
        if problems:
            status = "needs_human"
        elif rollback is None:
            status = "diagnosed"
        else:
            status = "mitigated" if "APPROVED" in str(rollback.content) else "mitigation_rejected"
        report = RootCauseReport(**base, status=status, **draft.model_dump(), problems=problems)
        return {"report": report.model_dump()}

    g = StateGraph(IncidentState)
    g.add_node("open_case", open_case)
    g.add_node("investigator", investigator)  # compiled create_agent graph as a subgraph node
    g.add_node("write_report", write_report)
    g.add_edge(START, "open_case")
    g.add_edge("open_case", "investigator")
    g.add_edge("investigator", "write_report")
    g.add_edge("write_report", END)
    return g.compile(checkpointer=checkpointer or MemorySaver())
