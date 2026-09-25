"""Planner + worker subgraphs + critic loop + compliance gate + assembly.

Parent:   plan 🤖 --Send per section--> section_worker (compiled subgraph) --> compliance
          --> assemble
Subgraph: next_question -> retrieve -> draft 🤖 -> critique
              pass -> accept -> next_question
              fail & budget left -> draft (with feedback)
              fail & (no KB hit | budget spent) -> needs_sme -> next_question
"""

from __future__ import annotations

import json
import operator
import re
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from rfp_agent import llm as prompts
from rfp_agent.knowledge import KB, parse_rfp
from rfp_agent.rules import CITE_RE, compliance_scan, critique, retrieve

MAX_REVISIONS = 2  # critic can send a draft back at most twice


class Question(BaseModel):
    id: str
    text: str


class Section(BaseModel):
    name: str
    questions: list[Question] = Field(min_length=1)


class SectionState(TypedDict, total=False):
    section: str
    questions: list[dict[str, str]]
    idx: int
    current: dict[str, Any]
    answers: Annotated[list[dict[str, Any]], operator.add]


class RfpState(TypedDict, total=False):
    rfp_text: str
    sections: list[dict[str, Any]]
    answers: Annotated[list[dict[str, Any]], operator.add]
    final_answers: list[dict[str, Any]]
    compliance: dict[str, Any]
    document: dict[str, Any]


class ResponseDoc(BaseModel):
    status: Literal["ready", "needs_sme", "legal_review_required"]
    markdown: str
    answered: int
    needs_sme: list[str]
    banned_claims_removed: list[str]
    export_control_hits: list[str]
    kb_ids_cited: list[str]


def _qnum(qid: str) -> int:
    return int(re.sub(r"\D", "", qid) or 0)


def build_section_graph(llm: BaseChatModel):
    def next_question(state: SectionState) -> dict[str, Any]:
        idx = state.get("idx", 0)
        if idx >= len(state["questions"]):
            return {"idx": idx, "current": {}}
        q = state["questions"][idx]
        return {
            "idx": idx,
            "current": {"id": q["id"], "question": q["text"], "attempts": 0, "issues": []},
        }

    def retrieve_kb(state: SectionState) -> dict[str, Any]:
        cur = state["current"]
        return {"current": {**cur, "retrieved": retrieve(cur["question"])}}

    def draft(state: SectionState) -> dict[str, Any]:
        cur = state["current"]
        payload = {
            "question": cur["question"],
            "kb": [{"id": k, **KB[k]} for k in cur["retrieved"]],
            "feedback": cur["issues"],
        }
        text = str(
            llm.invoke(
                [SystemMessage(prompts.DRAFT_SYSTEM), HumanMessage(json.dumps(payload))]
            ).content
        ).strip()
        return {"current": {**cur, "draft": text, "attempts": cur["attempts"] + 1}}

    def critic(state: SectionState) -> dict[str, Any]:
        cur = state["current"]
        issues = critique(cur["question"], cur["draft"], cur["retrieved"])
        return {"current": {**cur, "issues": issues}}

    def after_critic(state: SectionState) -> str:
        cur = state["current"]
        if not cur["issues"]:
            return "accept"
        if not cur["retrieved"] or cur["attempts"] > MAX_REVISIONS:
            return "needs_sme"
        return "draft"

    def record(state: SectionState, status: str) -> dict[str, Any]:
        cur = state["current"]
        ans = {
            "id": cur["id"],
            "section": state["section"],
            "question": cur["question"],
            "answer": cur["draft"] if status == "accepted" else "",
            "citations": sorted(set(CITE_RE.findall(cur["draft"]))),
            "attempts": cur["attempts"],
            "status": status,
            "issues": cur["issues"],
        }
        return {"answers": [ans], "idx": state["idx"] + 1}

    g = StateGraph(SectionState)
    g.add_node("next_question", next_question)
    g.add_node("retrieve", retrieve_kb)
    g.add_node("draft", draft)
    g.add_node("critique", critic)
    g.add_node("accept", lambda s: record(s, "accepted"))
    g.add_node("needs_sme", lambda s: record(s, "needs_sme"))
    g.add_edge(START, "next_question")
    g.add_conditional_edges(
        "next_question", lambda s: "retrieve" if s["current"] else END, ["retrieve", END]
    )
    g.add_edge("retrieve", "draft")
    g.add_edge("draft", "critique")
    g.add_conditional_edges("critique", after_critic, ["accept", "draft", "needs_sme"])
    g.add_edge("accept", "next_question")
    g.add_edge("needs_sme", "next_question")
    return g.compile()


def build_graph(llm: BaseChatModel | None = None):
    if llm is None:
        from shared.llm import get_llm

        llm = get_llm(mock_responder=prompts.mock_responder)
    section_graph = build_section_graph(llm)

    def plan(state: RfpState) -> dict[str, Any]:
        raw = str(
            llm.invoke(
                [SystemMessage(prompts.PLAN_SYSTEM), HumanMessage(state["rfp_text"])]
            ).content
        )
        try:
            m = re.search(r"\[.*\]", raw, re.S)
            sections = TypeAdapter(list[Section]).validate_json(m.group(0) if m else raw)
            planned = [s.model_dump() for s in sections]
        except ValidationError:
            planned = parse_rfp(state["rfp_text"])  # deterministic fallback planner
        return {"sections": planned}

    def fan_out(state: RfpState) -> list[Send]:
        return [
            Send("section_worker", {"section": s["name"], "questions": s["questions"]})
            for s in state["sections"]
        ]

    def compliance(state: RfpState) -> dict[str, Any]:
        out, removed_all, export_all = [], [], set()
        for a in sorted(state["answers"], key=lambda a: _qnum(a["id"])):
            text, removed, export = compliance_scan(a["answer"]) if a["answer"] else ("", [], [])
            a = {**a, "answer": text, "citations": sorted(set(CITE_RE.findall(text)))}
            if removed:
                a["compliance_removed"] = removed
                removed_all += [f"{a['id']}: {r}" for r in removed]
                if not a["citations"]:  # nothing citable left -> needs a human
                    a["status"] = "needs_sme"
            if export:
                a["export_control"] = export
                export_all |= set(export)
            out.append(a)
        return {
            "final_answers": out,
            "compliance": {
                "banned_claims_removed": removed_all,
                "export_control_hits": sorted(export_all),
            },
        }

    def assemble(state: RfpState) -> dict[str, Any]:
        ans = state["final_answers"]
        comp = state["compliance"]
        sme = [a["id"] for a in ans if a["status"] == "needs_sme"]
        status = (
            "legal_review_required"
            if comp["export_control_hits"]
            else "needs_sme"
            if sme
            else "ready"
        )
        title = state["rfp_text"].strip().splitlines()[0].lstrip("# ")
        md = [f"# Response to {title}", f"**Status:** {status}", ""]
        for sec in state["sections"]:
            md += [f"## {sec['name']}", ""]
            for a in (x for x in ans if x["section"] == sec["name"]):
                md.append(f"**{a['id']}. {a['question']}**")
                if a["status"] == "needs_sme":
                    md.append("> ⚠️ SME input required: no approved knowledge-base answer.")
                else:
                    md.append(CITE_RE.sub("", a["answer"]).replace(" .", ".").strip())
                    md.append(f"_Sources: {', '.join(a['citations'])}_")
                if a.get("export_control"):
                    md.append(f"> 🔒 Legal review: export-control terms {a['export_control']}")
                md.append("")
        cited = sorted({c for a in ans for c in a["citations"]})
        md += ["## Appendix: knowledge-base sources", *[f"- {k}: {KB[k]['title']}" for k in cited]]
        doc = ResponseDoc(
            status=status,
            markdown="\n".join(md),
            answered=sum(a["status"] == "accepted" for a in ans),
            needs_sme=sme,
            banned_claims_removed=comp["banned_claims_removed"],
            export_control_hits=comp["export_control_hits"],
            kb_ids_cited=cited,
        )
        return {"document": doc.model_dump()}

    g = StateGraph(RfpState)
    g.add_node("plan", plan)
    g.add_node("section_worker", section_graph)  # compiled subgraph as a node
    g.add_node("compliance", compliance)
    g.add_node("assemble", assemble)
    g.add_edge(START, "plan")
    g.add_conditional_edges("plan", fan_out, ["section_worker"])
    g.add_edge("section_worker", "compliance")
    g.add_edge("compliance", "assemble")
    g.add_edge("assemble", END)
    return g.compile()
