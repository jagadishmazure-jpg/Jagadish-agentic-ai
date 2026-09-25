"""Evaluator-optimizer loop.

segment -> classify_clauses 🤖 -> review (optimizer 🤖) -> evaluate (playbook evaluator)
    feedback & iterations < 3 -> review (revise with feedback)
    clean or budget spent     -> guardrails -> score_and_route -> END
"""

from __future__ import annotations

import json
import operator
import re
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field, ValidationError

from contract_review import llm as prompts
from contract_review.library import DISCLAIMER, LIBRARY, SEVERITY_RANK
from contract_review.rules import evaluate, expected_findings, score, segment, violates_guardrail

MAX_ITERATIONS = 3  # 1 draft + up to 2 revisions


class Finding(BaseModel):
    clause_id: str | None
    clause_type: str
    severity: Literal["low", "medium", "high", "critical"]
    issue: str
    evidence: str = ""
    redline: str = ""
    source: Literal["optimizer", "evaluator_enforced"] = "optimizer"


class ReviewReport(BaseModel):
    title: str
    findings: list[Finding]
    risk_score: int
    risk_tier: Literal["low", "medium", "high"]
    route: Literal["legal_review_required", "business_owner_review"]
    iterations: int
    evaluation_passed: bool
    unresolved_feedback: list[str] = Field(default_factory=list)
    guardrail_blocks: list[str] = Field(default_factory=list)
    disclaimer: str = DISCLAIMER


class ReviewState(TypedDict, total=False):
    text: str
    clauses: list[dict[str, Any]]
    expected: dict[str, dict[str, Any]]
    findings: list[dict[str, Any]]
    feedback: list[str]
    iterations: int
    history: Annotated[list[dict[str, Any]], operator.add]
    guardrail_blocks: list[str]
    report: dict[str, Any]


def build_graph(llm: BaseChatModel | None = None):
    if llm is None:
        from shared.llm import get_llm

        llm = get_llm(mock_responder=prompts.mock_responder)

    def ask(system: str, user: str) -> str:
        return str(llm.invoke([SystemMessage(system), HumanMessage(user)]).content).strip()

    def segment_node(state: ReviewState) -> dict[str, Any]:
        return {"clauses": segment(state["text"]), "iterations": 0, "feedback": []}

    def classify_clauses(state: ReviewState) -> dict[str, Any]:
        out = []
        for c in state["clauses"]:
            label = ask(prompts.CLASSIFY_SYSTEM, f"{c['heading']}\n{c['text']}").lower()
            ctype = next((t for t in prompts.TYPES if t in label), "other")
            out.append({**c, "type": ctype})
        return {"clauses": out, "expected": expected_findings(out, state["text"])}

    def review(state: ReviewState) -> dict[str, Any]:
        payload = {
            "clauses": state["clauses"],
            "playbook": {
                t: {"standard": s["standard"], "redline": s["redline"]} for t, s in LIBRARY.items()
            },
            "previous_findings": state.get("findings", []),
            "feedback": state["feedback"],
        }
        raw = ask(prompts.REVIEW_SYSTEM, json.dumps(payload))
        try:
            data = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
            findings = [Finding(**f).model_dump() for f in data.get("findings", [])]
        except (AttributeError, json.JSONDecodeError, ValidationError, TypeError):
            findings = []
        return {"findings": findings, "iterations": state["iterations"] + 1}

    def evaluate_node(state: ReviewState) -> dict[str, Any]:
        fb = evaluate(state["findings"], state["clauses"], state["expected"])
        return {
            "feedback": fb,
            "history": [
                {
                    "iteration": state["iterations"],
                    "findings": len(state["findings"]),
                    "feedback": fb,
                }
            ],
        }

    def after_eval(state: ReviewState) -> str:
        return (
            "review" if state["feedback"] and state["iterations"] < MAX_ITERATIONS else "guardrails"
        )

    def guardrails(state: ReviewState) -> dict[str, Any]:
        """Enforce the playbook floor and block unsafe redlines, whatever the model said."""
        exp = state["expected"]
        by_type = {f["clause_type"]: dict(f) for f in state["findings"] if f["clause_type"] in exp}
        blocks = []
        for ctype, e in exp.items():
            f = by_type.get(ctype)
            lib_redline = LIBRARY[ctype]["redline"]
            if f is None:
                by_type[ctype] = Finding(
                    clause_id=e["clause_id"],
                    clause_type=ctype,
                    severity=e["severity"],
                    issue=e["issue"],
                    evidence=e["evidence"],
                    redline=lib_redline,
                    source="evaluator_enforced",
                ).model_dump()
                continue
            if SEVERITY_RANK[f["severity"]] < SEVERITY_RANK[e["severity"]]:
                f.update(severity=e["severity"], source="evaluator_enforced")
            if any(t.lower() not in f["redline"].lower() for t in LIBRARY[ctype]["required_terms"]):
                f.update(redline=lib_redline, source="evaluator_enforced")
            hit = violates_guardrail(f["redline"])
            if hit:
                blocks.append(f"{ctype}: redline matched prohibited pattern {hit!r}")
                f["redline"] = lib_redline
            by_type[ctype] = f
        return {"findings": list(by_type.values()), "guardrail_blocks": blocks}

    def score_and_route(state: ReviewState) -> dict[str, Any]:
        findings = sorted(state["findings"], key=lambda f: -SEVERITY_RANK[f["severity"]])
        s, tier = score(findings)
        critical = any(f["severity"] in ("critical", "high") for f in findings)
        title = state["text"].strip().splitlines()[0]
        report = ReviewReport(
            title=title,
            findings=[Finding(**f) for f in findings],
            risk_score=s,
            risk_tier=tier,
            route="legal_review_required" if critical else "business_owner_review",
            iterations=state["iterations"],
            evaluation_passed=not state["feedback"],
            unresolved_feedback=state["feedback"],
            guardrail_blocks=state.get("guardrail_blocks", []),
        )
        return {"report": report.model_dump()}

    g = StateGraph(ReviewState)
    g.add_node("segment", segment_node)
    g.add_node("classify_clauses", classify_clauses)
    g.add_node("review", review)
    g.add_node("evaluate", evaluate_node)
    g.add_node("guardrails", guardrails)
    g.add_node("score_and_route", score_and_route)
    g.add_edge(START, "segment")
    g.add_edge("segment", "classify_clauses")
    g.add_edge("classify_clauses", "review")
    g.add_edge("review", "evaluate")
    g.add_conditional_edges("evaluate", after_eval, ["review", "guardrails"])
    g.add_edge("guardrails", "score_and_route")
    g.add_edge("score_and_route", END)
    return g.compile()
