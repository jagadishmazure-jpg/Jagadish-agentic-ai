"""Evaluator-optimizer loop.

segment -> classify_clauses 🤖 -> review (optimizer 🤖) -> evaluate (playbook evaluator)
    feedback & iterations < 3 -> review (revise with feedback)
    clean or budget spent     -> guardrails -> score_and_route -> END

Doctrine wiring: the playbook text the reviewer reads is retrieved per clause from the shared
ContextBuilder (ACL: senior-counsel fallbacks never reach the review agent); the rules engine
+ guardrails remain the deterministic control. Model outage -> keyword classifier and a
rules-only review (the evaluator floor supplies findings and approved redlines); playbook
search outage -> rules-only review; contract text is sanitised and suspected injection forces
legal review. Exits go to ``state["exits"]``.
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
from contract_review.playbook import builder as playbook_builder
from contract_review.playbook import playbook_context
from contract_review.rules import (
    evaluate,
    expected_findings,
    keyword_type,
    score,
    segment,
    violates_guardrail,
)
from shared.context import ContextBuilder, RetrievalError, looks_like_injection, sanitize
from shared.observability import install
from shared.resilience import ModelUnavailableError, exit_record, with_fallback

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
    playbook_sources: list[str] = Field(default_factory=list)
    injection_suspected: bool = False
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
    injection: bool
    playbook_sources: list[str]
    exits: Annotated[list[dict[str, str]], operator.add]


def build_graph(llm: BaseChatModel | None = None, kb: ContextBuilder | None = None):
    install()
    if llm is None:
        from shared.llm import get_llm

        llm = get_llm(mock_responder=prompts.mock_responder)
    llm = with_fallback(llm)
    kb = kb or playbook_builder()

    def ask(system: str, user: str) -> str:
        return str(llm.invoke([SystemMessage(system), HumanMessage(user)]).content).strip()

    def segment_node(state: ReviewState) -> dict[str, Any]:
        clauses = segment(state["text"])
        injection = any(looks_like_injection(c["text"]) for c in clauses)
        exits = []
        if injection:  # contract text is untrusted: neutralise before any model sees it
            clauses = [{**c, "text": sanitize(c["text"], redact_pii=False).text} for c in clauses]
            exits = [exit_record("segment", "escalate", "suspected prompt injection -> legal")]
        return {
            "clauses": clauses,
            "iterations": 0,
            "feedback": [],
            "injection": injection,
            "exits": exits,
        }

    def classify_clauses(state: ReviewState) -> dict[str, Any]:
        out, degraded = [], False
        for c in state["clauses"]:
            try:
                label = ask(prompts.CLASSIFY_SYSTEM, f"{c['heading']}\n{c['text']}").lower()
                ctype = next((t for t in prompts.TYPES if t in label), "other")
            except ModelUnavailableError:
                ctype, degraded = keyword_type(c["heading"], c["text"]), True
            out.append({**c, "type": ctype})
        exits = (
            [exit_record("classify_clauses", "degrade", "model unavailable: keyword classifier")]
            if degraded
            else []
        )
        return {
            "clauses": out,
            "expected": expected_findings(out, state["text"]),
            "exits": exits,
        }

    def review(state: ReviewState) -> dict[str, Any]:
        n = state["iterations"] + 1
        try:
            playbook = playbook_context(kb, state["clauses"])
        except RetrievalError as exc:
            return {
                "findings": [],
                "iterations": MAX_ITERATIONS,
                "exits": [exit_record("review", "degrade", f"{exc}: rules-only review")],
            }
        payload = {
            "clauses": state["clauses"],
            "playbook": playbook,
            "previous_findings": state.get("findings", []),
            "feedback": state["feedback"],
        }
        try:
            raw = ask(prompts.REVIEW_SYSTEM, json.dumps(payload))
        except ModelUnavailableError:
            return {
                "findings": [],
                "iterations": MAX_ITERATIONS,  # no point looping without a model
                "playbook_sources": sorted(p["id"] for p in playbook.values()),
                "exits": [exit_record("review", "degrade", "model unavailable: rules-only")],
            }
        try:
            data = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
            findings = [Finding(**f).model_dump() for f in data.get("findings", [])]
        except (AttributeError, json.JSONDecodeError, ValidationError, TypeError):
            findings = []
        return {
            "findings": findings,
            "iterations": n,
            "playbook_sources": sorted(p["id"] for p in playbook.values()),
        }

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
        critical = critical or bool(state.get("injection"))
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
            playbook_sources=state.get("playbook_sources", []),
            injection_suspected=bool(state.get("injection")),
        )
        exits = []
        if report.route == "legal_review_required":
            exits.append(exit_record("score_and_route", "escalate", "legal review required"))
        return {"report": report.model_dump(), "exits": exits}

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
    compiled = g.compile(name="contract-review")
    compiled.kb = kb
    return compiled
