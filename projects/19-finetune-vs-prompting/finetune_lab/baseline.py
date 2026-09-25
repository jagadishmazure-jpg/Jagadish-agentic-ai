"""Baseline: the base chat model with a prompt (rubric + few-shot), no training.

Offline the base model is the shared ``MockChatModel`` with ``mock_responder`` below. The
responder reads the rubric *from the system prompt it is given* (the ``Cues:`` list per
label) and matches those cues in the OCR text, so its behaviour comes from the prompt,
like a zero-shot model reading instructions. Canonical headings classify well; alternate
titles, garbled OCR and untitled pages do not. That is the gap fine-tuning is meant to
close. With ``--live`` the same prompt goes to the configured Azure OpenAI / OpenAI
deployment instead.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage

from finetune_lab.labels import LABELS, SYSTEM_PROMPT_BASELINE
from shared.observability import estimate_tokens
from shared.resilience import with_fallback

_RUBRIC = re.compile(r"^- (\w+): .*? Cues: (.*)\.$", re.M)


def mock_responder(messages: Sequence[BaseMessage]) -> str:
    system = str(messages[0].content) if messages else ""
    doc = str(messages[-1].content).lower()
    scores: dict[str, int] = {}
    for label, cues in _RUBRIC.findall(system):
        scores[label] = sum(cue.strip() in doc for cue in cues.split(","))
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    if not ranked or ranked[0][1] == 0:
        return json.dumps({"label": "unknown", "confidence": 0.2})
    best, second = ranked[0][1], ranked[1][1] if len(ranked) > 1 else 0
    conf = max(0.05, min(0.95, 0.5 + 0.15 * best - 0.1 * second))
    return json.dumps({"label": ranked[0][0], "confidence": round(conf, 2)})


@dataclass
class Prediction:
    label: str
    confidence: float
    input_tokens: int
    output_tokens: int
    served_by: str = ""


def parse(raw: str) -> tuple[str, float]:
    m = re.search(r"\{.*\}", raw, re.S)
    try:
        obj = json.loads(m.group(0) if m else raw)
        label, conf = str(obj.get("label", "unknown")), float(obj.get("confidence", 0.0))
    except (json.JSONDecodeError, TypeError, ValueError, AttributeError):
        return "unknown", 0.0
    return (label if label in LABELS else "unknown"), max(0.0, min(1.0, conf))


class PromptedClassifier:
    """Base model + rubric prompt. Raises ``ModelUnavailableError`` when every deployment is
    down (the graph degrades to human review)."""

    kind = "prompt"
    version = "prompt-baseline"

    def __init__(self, llm: BaseChatModel | None = None, prompt: str = SYSTEM_PROMPT_BASELINE):
        if llm is None:
            from shared.llm import get_llm

            llm = get_llm(mock_responder=mock_responder)
        self.llm = with_fallback(llm)
        self.prompt = prompt

    def predict(self, text: str) -> Prediction:
        msg = self.llm.invoke([SystemMessage(self.prompt), HumanMessage(text)])
        raw = str(msg.content)
        label, conf = parse(raw)
        return Prediction(
            label,
            conf,
            estimate_tokens(self.prompt) + estimate_tokens(text),
            estimate_tokens(raw),
            str(msg.response_metadata.get("served_by", "primary")),
        )
