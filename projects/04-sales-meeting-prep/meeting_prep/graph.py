"""Parallel fan-out / fan-in.

plan --Send x N--> research(source)  (all run in ONE super-step, concurrently)
     reducers merge findings/errors/timings --> synthesize --> render_brief
A failing branch writes an error record instead of raising, so the brief is still produced
(with the gap called out). Below a quorum of sources, the brief is marked insufficient.
"""

from __future__ import annotations

import json
import operator
import re
import time
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel, Field

from meeting_prep import llm as prompts
from meeting_prep.sources import Sources

ALL_SOURCES = ("crm", "news", "deals", "support")
MIN_SOURCES = 2
MAX_ATTEMPTS = 2  # one retry for transient errors
TRANSIENT = (TimeoutError, ConnectionError)
ID_RE = re.compile(r"\[([A-Z]+-\d+)\]")


def merge(left: dict | None, right: dict | None) -> dict:
    return {**(left or {}), **(right or {})}


class ResearchTask(TypedDict):
    source: str
    account_id: str


class PrepState(TypedDict, total=False):
    account_id: str
    account_name: str
    meeting: dict[str, Any]
    sources: list[str]
    findings: Annotated[dict[str, dict[str, Any]], merge]  # parallel-safe
    errors: Annotated[list[str], operator.add]
    timings: Annotated[list[dict[str, Any]], operator.add]
    synthesis: dict[str, Any]
    brief: dict[str, Any]


class Brief(BaseModel):
    account: str
    status: Literal["complete", "partial", "insufficient_data"]
    markdown: str
    sources_used: list[str]
    gaps: list[str] = Field(default_factory=list)
    talking_points: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)


def build_graph(sources: Sources, llm: BaseChatModel | None = None):
    if llm is None:
        from shared.llm import get_llm

        llm = get_llm(mock_responder=prompts.mock_responder)
    fetchers = sources.fetchers()

    def plan(state: PrepState) -> dict[str, Any]:
        return {"sources": list(state.get("sources") or ALL_SOURCES)}

    def fan_out(state: PrepState) -> list[Send]:
        return [
            Send("research", {"source": s, "account_id": state["account_id"]})
            for s in state["sources"]
        ]

    def research(task: ResearchTask) -> dict[str, Any]:
        src, t0, attempts = task["source"], time.perf_counter(), 0
        while True:
            attempts += 1
            try:
                items = fetchers[src](task["account_id"])
                record = {"status": "ok", "items": items, "attempts": attempts}
                errors: list[str] = []
                break
            except TRANSIENT as e:
                if attempts < MAX_ATTEMPTS:
                    continue
                record, errors = (
                    {"status": "error", "error": repr(e), "attempts": attempts},
                    [f"{src}: {e!r} after {attempts} attempts"],
                )
                break
            except Exception as e:  # non-transient: don't retry, don't crash the brief
                record = {"status": "error", "error": repr(e), "attempts": attempts}
                errors = [f"{src}: {e!r}"]
                break
        ms = round((time.perf_counter() - t0) * 1000, 1)
        return {
            "findings": {src: record},
            "errors": errors,
            "timings": [{"source": src, "ms": ms, "status": record["status"]}],
        }

    def synthesize(state: PrepState) -> dict[str, Any]:
        ok = {s: f for s, f in state["findings"].items() if f["status"] == "ok"}
        valid_ids = {i["id"] for f in ok.values() for i in f["items"]}
        payload = {
            "account": state["account_name"],
            "meeting": state.get("meeting", {}),
            "findings": ok,
        }
        raw = str(
            llm.invoke(
                [SystemMessage(prompts.SYNTH_SYSTEM), HumanMessage(json.dumps(payload))]
            ).content
        )
        try:
            data = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        except (AttributeError, json.JSONDecodeError):
            data = {"talking_points": [], "risks": []}

        def cited(bullets: list[str]) -> tuple[list[str], int]:
            keep = [b for b in bullets if ID_RE.findall(b) and set(ID_RE.findall(b)) <= valid_ids]
            return keep, len(bullets) - len(keep)

        points, dropped_p = cited(data.get("talking_points", []))
        risks, dropped_r = cited(data.get("risks", []))
        return {
            "synthesis": {
                "talking_points": points,
                "risks": risks,
                "dropped_uncited": dropped_p + dropped_r,
            }
        }

    def render_brief(state: PrepState) -> dict[str, Any]:
        f = state["findings"]
        ok = [s for s in state["sources"] if f.get(s, {}).get("status") == "ok"]
        gaps = [s for s in state["sources"] if s not in ok]
        status = "insufficient_data" if len(ok) < MIN_SOURCES else "partial" if gaps else "complete"
        syn = state["synthesis"]
        m = state.get("meeting", {})
        items = {s: f[s]["items"] for s in ok}
        md = [
            f"# Meeting brief: {state['account_name']}",
            f"**When:** {m.get('date', 'n/a')} · **Attendees:** "
            f"{', '.join(m.get('attendees', [])) or 'n/a'} · **Goal:** {m.get('goal', 'n/a')}",
            f"**Status:** {status}" + (f" (missing: {', '.join(gaps)})" if gaps else ""),
            "",
        ]
        if status == "insufficient_data":
            md += [
                "> ⚠️ Not enough sources responded to produce a reliable brief. "
                "Check the CRM directly before the meeting.",
                "",
            ]
        points = [f"- {p}" for p in syn["talking_points"]] or ["- (none)"]
        risks = [f"- {r}" for r in syn["risks"]] or ["- (none identified)"]
        md += ["## Talking points", *points, "", "## Risks", *risks, ""]
        if "deals" in items:
            md += [
                "## Open deals",
                "| ID | Deal | Amount | Stage | Close |",
                "|---|---|---|---|---|",
                *[
                    f"| {d['id']} | {d['name']} | ${d['amount']:,} | {d['stage']} | {d['close']} |"
                    for d in items["deals"]
                ],
                "",
            ]
        if "crm" in items:
            md += [
                "## Recent interactions",
                *[
                    f"- {i['date']} {i['type']}: {i['note']} [{i['id']}]"
                    for i in sorted(items["crm"], key=lambda i: i["date"], reverse=True)
                ],
                "",
            ]
        if "support" in items:
            md += [
                "## Support health",
                *[
                    f"- {t['priority']} {t['status']}: {t['subject']} [{t['id']}]"
                    for t in items["support"]
                ],
                "",
            ]
        if "news" in items:
            md += [
                "## News",
                *[f"- {n['date']} {n['headline']} [{n['id']}]({n['url']})" for n in items["news"]],
                "",
            ]
        if gaps:
            md += [
                "## Gaps",
                *[f"- **{s}** unavailable: {f[s]['error']}. Verify manually." for s in gaps],
                "",
            ]
        md += ["## Sources", f"Used: {', '.join(ok) or 'none'}."]
        brief = Brief(
            account=state["account_name"],
            status=status,
            markdown="\n".join(md),
            sources_used=ok,
            gaps=gaps,
            talking_points=syn["talking_points"],
            risks=syn["risks"],
        )
        return {"brief": brief.model_dump()}

    g = StateGraph(PrepState)
    g.add_node("plan", plan)
    g.add_node("research", research, input_schema=ResearchTask)
    g.add_node("synthesize", synthesize)
    g.add_node("render_brief", render_brief)
    g.add_edge(START, "plan")
    g.add_conditional_edges("plan", fan_out, ["research"])
    g.add_edge("research", "synthesize")  # fan-in: runs once after all research branches
    g.add_edge("synthesize", "render_brief")
    g.add_edge("render_brief", END)
    return g.compile()
