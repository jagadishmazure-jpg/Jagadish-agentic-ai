"""Serving graph: the registry's champion classifies each uploaded loan document.

intake (scrub PII, injection check) -> classify (champion; fallback to the prompted
baseline) -> confidence gate -> file_document | human_review

* ``intake`` scrubs PII before any model sees the page. Text that looks like injected
  instructions is escalated to a processor, never auto-filed.
* ``classify`` serves the registry champion. If the champion is the fine-tuned model and
  its deployment is down (or its artifact fails the hash check) the prompted baseline
  answers instead (degrade, recorded in ``exits``). If every model is down the document
  goes to human review; the graph never guesses a type.
* The gate files only labels with confidence >= ``CONFIDENCE_FLOOR``; everything else, and
  ``unknown``, is queued for a processor.
* Filing and queueing are idempotent LOS writes over MCP; an LOS outage parks the write
  in an outbox for replay.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph

from finetune_lab.baseline import PromptedClassifier
from finetune_lab.pii import scrub
from finetune_lab.registry import ArtifactIntegrityError, ModelRegistry
from finetune_lab.sor import LosBackend, build_gateway
from shared.context import looks_like_injection
from shared.observability import install
from shared.resilience import ModelUnavailableError, exit_record
from shared.tools import SystemOfRecordUnavailableError

CONFIDENCE_FLOOR = 0.55


class DocState(TypedDict, total=False):
    doc: dict[str, str]
    text: str
    redactions: dict[str, int]
    injection: bool
    prediction: dict[str, Any] | None
    result: dict[str, Any]
    trace: Annotated[list[str], operator.add]
    exits: Annotated[list[dict[str, str]], operator.add]


def build_graph(
    registry: ModelRegistry | None = None,
    los: LosBackend | None = None,
    outbox: list[dict[str, Any]] | None = None,
    llm: Any = None,
):
    install()
    if registry is None:
        from finetune_lab.compare import load_registry

        registry = load_registry()
    los = los if los is not None else LosBackend()
    outbox = outbox if outbox is not None else []
    gw = build_gateway(los)
    fallback = PromptedClassifier(llm=llm)
    fallback.version = next(
        (e.version for e in registry.entries.values() if e.kind == "prompt"), "prompt-baseline"
    )

    def write(node: str, tool: str, **args: Any) -> tuple[str | None, list[dict[str, str]]]:
        try:
            out = gw.call("los", tool, dry_run=False, **args)
            return out["status"], []
        except SystemOfRecordUnavailableError as exc:
            outbox.append({"system": "los", "tool": tool, **args})
            return None, [exit_record(node, "degrade", f"LOS unavailable, queued: {exc}")]

    def intake(state: DocState) -> dict[str, Any]:
        text, counts = scrub(state["doc"]["text"])
        injection = looks_like_injection(text)
        exits = (
            [exit_record("intake", "escalate", "suspected prompt injection")] if injection else []
        )
        return {
            "text": text,
            "redactions": dict(counts),
            "injection": injection,
            "prediction": None,
            "trace": ["intake"],
            "exits": exits,
        }

    def classify(state: DocState) -> dict[str, Any]:
        exits = []
        try:
            clf = registry.classifier(llm=llm)
        except ArtifactIntegrityError as exc:
            clf = fallback
            exits.append(exit_record("classify", "degrade", f"champion refused: {exc}"))
        candidates = [clf] if clf is fallback else [clf, fallback]
        for i, c in enumerate(candidates):
            try:
                p = c.predict(state["text"])
            except ModelUnavailableError:
                if i + 1 < len(candidates):
                    exits.append(exit_record("classify", "degrade", "champion down: fallback"))
                continue
            pred = {
                "label": p.label,
                "confidence": round(p.confidence, 4),
                "model_version": c.version,
            }
            return {"prediction": pred, "trace": ["classify"], "exits": exits}
        down = exit_record("classify", "degrade", "all models down: human review")
        return {"trace": ["classify"], "exits": [*exits, down]}

    def route(state: DocState) -> str:
        if state.get("injection"):
            return "human_review"
        p = state.get("prediction")
        if not p or p["label"] == "unknown" or p["confidence"] < CONFIDENCE_FLOOR:
            return "human_review"
        return "file_document"

    def file_document(state: DocState) -> dict[str, Any]:
        d, p = state["doc"], state["prediction"]
        assert p is not None
        status, exits = write(
            "file_document",
            "file_document",
            loan_id=d["loan_id"],
            doc_id=d["doc_id"],
            doc_type=p["label"],
            confidence=p["confidence"],
            model_version=p["model_version"],
            idempotency_key=f"classify:{d['doc_id']}",
        )
        result = {"route": "filed", "doc_type": p["label"], "los_status": status, **p}
        return {"result": result, "trace": ["file_document"], "exits": exits}

    def human_review(state: DocState) -> dict[str, Any]:
        d, p = state["doc"], state.get("prediction")
        if state.get("injection"):
            reason = "suspected prompt injection in document text"
        elif p is None:
            reason = "classifier unavailable (all model deployments down)"
        elif p["label"] == "unknown":
            reason = "no document type matched"
        else:
            reason = f"confidence {p['confidence']:.2f} < {CONFIDENCE_FLOOR} for {p['label']}"
        status, exits = write(
            "human_review",
            "queue_review",
            loan_id=d["loan_id"],
            doc_id=d["doc_id"],
            reason=reason,
            idempotency_key=f"classify:{d['doc_id']}",
        )
        result = {"route": "human_review", "reason": reason, "los_status": status}
        if p:
            result.update({"suggested": p["label"], "confidence": p["confidence"]})
        return {"result": result, "trace": ["human_review"], "exits": exits}

    g = StateGraph(DocState)
    g.add_node("intake", intake)
    g.add_node("classify", classify)
    g.add_node("file_document", file_document)
    g.add_node("human_review", human_review)
    g.add_edge(START, "intake")
    g.add_conditional_edges(
        "intake",
        lambda s: "human_review" if s["injection"] else "classify",
        ["classify", "human_review"],
    )
    g.add_conditional_edges("classify", route, ["file_document", "human_review"])
    g.add_edge("file_document", END)
    g.add_edge("human_review", END)
    compiled = g.compile(name="doc-classifier")
    compiled.registry, compiled.los, compiled.outbox, compiled.gateway = registry, los, outbox, gw
    return compiled
