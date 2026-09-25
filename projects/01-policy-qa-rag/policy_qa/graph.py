"""Corrective RAG graph.

rewrite_query -> retrieve (+sanitize) -> grade_chunks
    relevant           -> pack_context -> generate_answer -> check_groundedness
                             grounded -> finalize | ungrounded -> insufficient_evidence
    weak & attempt < 2 -> rewrite_query (expanded) -> retrieve ...
    weak & attempt = 2 -> insufficient_evidence

Doctrine wiring: retrieval goes through the shared ContextBuilder (hybrid BM25 + vector with
RRF, ACL trim by principal, as-of temporal filter); the model is a fallback chain and each
LLM step has a deterministic degrade (lexical rewrite / lexical grader / extractive answer);
a retrieval outage takes the honest insufficient-evidence exit. Exits land in state["exits"].
"""

from __future__ import annotations

import operator
import re
from datetime import date
from typing import Annotated, Any, Literal, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from policy_qa import llm as prompts
from policy_qa.guards import CITATION_RE, groundedness, pack_context, sanitize
from policy_qa.knowledge import ContextBuilderRetriever, default_retriever
from policy_qa.retriever import Retriever
from shared.context import Principal, RetrievalUnavailableError
from shared.observability import install
from shared.resilience import ModelUnavailableError, exit_record, with_fallback

MAX_ATTEMPTS = 2


class Citation(BaseModel):
    id: str
    doc: str
    section: str


class Answer(BaseModel):
    status: Literal["answered", "insufficient_evidence"]
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    attempts: int
    queries: list[str]
    grounded: bool
    flagged_injections: list[str] = Field(default_factory=list)
    reason: str = ""


class RagState(TypedDict, total=False):
    question: str
    principal: dict[str, Any]  # {"id", "groups": [...], "tenant"} - ACL scope
    as_of: str  # ISO date of the business event (temporal policy retrieval)
    exits: Annotated[list[dict[str, str]], operator.add]
    unavailable: bool
    attempts: int
    query: str
    queries: Annotated[list[str], operator.add]
    retrieved: list[dict[str, Any]]
    relevant: list[dict[str, Any]]
    flagged: Annotated[list[str], operator.add]
    context: list[dict[str, Any]]
    draft: str
    check: dict[str, Any]
    trace: Annotated[list[str], operator.add]
    final: dict[str, Any]


def _normalize_citations(text: str) -> str:
    """Move citations that follow a period in front of it: 'x. [ID]' -> 'x [ID].'"""
    return re.sub(
        r"\.\s*((?:\[[A-Z]+-[A-Z]+-\d+\]\s*)+)", lambda m: f" {m.group(1).strip()}. ", text
    ).strip()


def build_graph(
    retriever: Retriever | None = None,
    llm: BaseChatModel | None = None,
    *,
    k: int = 4,
    budget_tokens: int = 350,
):
    install()
    if llm is None:
        from shared.llm import get_llm

        llm = get_llm(mock_responder=prompts.mock_responder)
    llm = with_fallback(llm)
    retriever = retriever or default_retriever()

    def ask(system: str, user: str) -> str:
        return str(llm.invoke([SystemMessage(system), HumanMessage(user)]).content).strip()

    def scoped(state: RagState) -> Retriever:
        if isinstance(retriever, ContextBuilderRetriever) and (
            state.get("principal") or state.get("as_of")
        ):
            p = state.get("principal")
            principal = (
                Principal(p["id"], frozenset(p.get("groups", [])), p.get("tenant")) if p else None
            )
            as_of = date.fromisoformat(state["as_of"]) if state.get("as_of") else None
            return retriever.with_scope(principal, as_of)
        return retriever

    def rewrite_query(state: RagState) -> dict[str, Any]:
        attempt = state.get("attempts", 0) + 1
        exits = []
        try:
            q = ask(prompts.REWRITE_SYSTEM.format(attempt=attempt), state["question"])
        except ModelUnavailableError:
            q = prompts.mock_rewrite(state["question"], attempt)  # deterministic rewrite
            exits.append(exit_record("rewrite_query", "degrade", "lexical rewrite"))
        if attempt > 1:  # keep the original words too, so expansion never loses recall
            q = f"{state['question']} {q}"
        return {
            "attempts": attempt,
            "query": q,
            "queries": [q],
            "trace": ["rewrite_query"],
            "exits": exits,
        }

    def retrieve(state: RagState) -> dict[str, Any]:
        hits, flagged = [], []
        try:
            found = scoped(state).search(state["query"], k=k)
        except RetrievalUnavailableError as exc:
            return {
                "retrieved": [],
                "unavailable": True,
                "trace": ["retrieve"],
                "exits": [exit_record("retrieve", "degrade", f"{exc}: answer withheld")],
            }
        for h in found:
            clean, removed = sanitize(h.chunk.text)  # before ANY model sees retrieved text
            flagged += [f"{h.chunk.id}: {r}" for r in removed]
            hits.append(
                {
                    "id": h.chunk.id,
                    "doc": h.chunk.doc,
                    "section": h.chunk.section,
                    "text": clean,
                    "score": h.score,
                }
            )
        exits = (
            [exit_record("retrieve", "degrade", f"{len(flagged)} injected span(s) neutralised")]
            if flagged
            else []
        )
        return {"retrieved": hits, "flagged": flagged, "trace": ["retrieve"], "exits": exits}

    def grade_chunks(state: RagState) -> dict[str, Any]:
        relevant, exits = [], []
        for c in state["retrieved"]:
            user = (
                f"Question: {state['question']}\nSearch query: {state['query']}\n"
                f"Document: {c['section']}. {c['text']}"
            )
            try:
                verdict = ask(prompts.GRADE_SYSTEM, user)
            except ModelUnavailableError:
                verdict = prompts.mock_grade(state["query"], f"{c['section']}. {c['text']}")
                exits = [exit_record("grade_chunks", "degrade", "lexical grader")]
            if verdict.lower().startswith("yes"):
                relevant.append(c)
        return {"relevant": relevant, "trace": ["grade_chunks"], "exits": exits}

    def after_grade(state: RagState) -> str:
        if state.get("unavailable"):
            return "insufficient_evidence"
        if state["relevant"]:
            return "pack_context"
        return "rewrite_query" if state["attempts"] < MAX_ATTEMPTS else "insufficient_evidence"

    def pack(state: RagState) -> dict[str, Any]:
        return {
            "context": pack_context(state["relevant"], budget_tokens),
            "trace": ["pack_context"],
        }

    def generate_answer(state: RagState) -> dict[str, Any]:
        docs = "\n".join(
            f'<document id="{c["id"]}">{c["text"]}</document>' for c in state["context"]
        )
        user = (
            f"Question: {state['question']}\nSearch query: {state['query']}\n\n"
            f"<documents>\n{docs}\n</documents>"
        )
        exits = []
        try:
            draft = ask(prompts.ANSWER_SYSTEM, user)
        except ModelUnavailableError:
            # Limited but true: extractive, cited sentences from the packed evidence.
            draft = prompts.mock_answer(f"{state['question']} {state['query']}", user)
            exits.append(exit_record("generate_answer", "degrade", "extractive answer"))
        return {
            "draft": _normalize_citations(draft),
            "trace": ["generate_answer"],
            "exits": exits,
        }

    def check_groundedness(state: RagState) -> dict[str, Any]:
        if "INSUFFICIENT_EVIDENCE" in state["draft"]:
            check = {
                "grounded": False,
                "problems": ["model reported insufficient evidence"],
                "citations": [],
            }
        else:
            check = groundedness(state["draft"], state["context"])
        return {"check": check, "trace": ["check_groundedness"]}

    def after_check(state: RagState) -> str:
        return "finalize" if state["check"]["grounded"] else "insufficient_evidence"

    def finalize(state: RagState) -> dict[str, Any]:
        by_id = {c["id"]: c for c in state["context"]}
        cites = [
            Citation(id=i, doc=by_id[i]["doc"], section=by_id[i]["section"])
            for i in state["check"]["citations"]
        ]
        final = Answer(
            status="answered",
            answer=state["draft"],
            citations=cites,
            attempts=state["attempts"],
            queries=state["queries"],
            grounded=True,
            flagged_injections=sorted(set(state.get("flagged", []))),
        )
        return {"final": final.model_dump(), "trace": ["finalize"]}

    def insufficient_evidence(state: RagState) -> dict[str, Any]:
        if state.get("unavailable"):
            reason = "policy search is temporarily unavailable"
        elif "check" in state:
            reason = "; ".join(state["check"]["problems"])
        else:
            reason = f"no relevant policy sections after {state['attempts']} retrieval attempts"
        final = Answer(
            status="insufficient_evidence",
            answer="I couldn't find this in the policy documents I have access to. "
            "Please contact HR (hr@example.com) or IT (#it-help) for a definitive answer.",
            attempts=state["attempts"],
            queries=state["queries"],
            grounded=False,
            flagged_injections=sorted(set(state.get("flagged", []))),
            reason=reason,
        )
        return {"final": final.model_dump(), "trace": ["insufficient_evidence"]}

    g = StateGraph(RagState)
    g.add_node("rewrite_query", rewrite_query)
    g.add_node("retrieve", retrieve)
    g.add_node("grade_chunks", grade_chunks)
    g.add_node("pack_context", pack)
    g.add_node("generate_answer", generate_answer)
    g.add_node("check_groundedness", check_groundedness)
    g.add_node("finalize", finalize)
    g.add_node("insufficient_evidence", insufficient_evidence)
    g.add_edge(START, "rewrite_query")
    g.add_edge("rewrite_query", "retrieve")
    g.add_edge("retrieve", "grade_chunks")
    g.add_conditional_edges(
        "grade_chunks", after_grade, ["pack_context", "rewrite_query", "insufficient_evidence"]
    )
    g.add_edge("pack_context", "generate_answer")
    g.add_edge("generate_answer", "check_groundedness")
    g.add_conditional_edges(
        "check_groundedness", after_check, ["finalize", "insufficient_evidence"]
    )
    g.add_edge("finalize", END)
    g.add_edge("insufficient_evidence", END)
    return g.compile(name="policy-qa-rag")


__all__ = ["CITATION_RE", "Answer", "build_graph"]
