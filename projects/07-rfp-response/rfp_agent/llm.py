"""Planner + drafter prompts and deterministic mocks."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

from langchain_core.messages import BaseMessage

from rfp_agent.knowledge import parse_rfp

PLAN_SYSTEM = (
    "TASK: PLAN\n"
    "Split the RFP into sections and questions. Reply with JSON: "
    '[{"name": "...", "questions": [{"id": "Q1", "text": "..."}]}]'
)
DRAFT_SYSTEM = (
    "TASK: DRAFT\n"
    "Answer the RFP question using ONLY the provided knowledge-base entries. End every "
    "sentence with the KB id it comes from, e.g. [KB-SEC-001]. Max 120 words. If the entries "
    "don't answer the question reply exactly NO_KB_ANSWER. If reviewer feedback is present, "
    "fix every issue it lists."
)


def _cite_sentences(kid: str, text: str) -> str:
    sentences = [s.strip().rstrip(".") for s in re.split(r"(?<=\.)\s+", text) if s.strip()]
    return " ".join(f"{s} [{kid}]." for s in sentences)


def mock_draft(payload: dict) -> str:
    kb = payload["kb"]
    if not kb:
        return "NO_KB_ANSWER"
    chosen = [kb[0]]  # first pass: lean answer from the single best entry
    missing = []
    for fb in payload.get("feedback", []):
        m = re.search(r"does not address: \[(.*)\]", fb)
        if m:
            missing += [x.strip(" '\"") for x in m.group(1).split(",")]
    for facet in missing:
        chosen += [e for e in kb if facet in e["text"].lower() and e not in chosen]
    return " ".join(_cite_sentences(e["id"], e["text"]) for e in chosen)


def mock_responder(messages: Sequence[BaseMessage]) -> str:
    system, user = str(messages[0].content), str(messages[-1].content)
    if system.startswith("TASK: PLAN"):
        return json.dumps(parse_rfp(user))
    if system.startswith("TASK: DRAFT"):
        return mock_draft(json.loads(user))
    return "[mock] unsupported task"
