"""Prompt-injection sanitizer, token-budget packer and groundedness check."""

from __future__ import annotations

import re
from typing import Any

from policy_qa.text import estimate_tokens, tokens

INJECTION_PATTERNS = [
    r"ignore (all )?(previous|prior|above) instructions[^.]*\.?",
    r"disregard (the )?(system|previous) prompt[^.]*\.?",
    r"you are now [^.]*\.?",
    r"(^|\s)system\s*:[^.]*\.?",
    r"<\s*/?\s*(script|system|instructions?)[^>]*>",
]
_INJECTION_RE = re.compile("|".join(INJECTION_PATTERNS), re.IGNORECASE)


def sanitize(text: str) -> tuple[str, list[str]]:
    """Remove instruction-like spans from retrieved text. Returns (clean_text, removed_spans)."""
    removed = [m.group(0).strip() for m in _INJECTION_RE.finditer(text)]
    clean = _INJECTION_RE.sub(" [removed: instruction-like text] ", text)
    return re.sub(r"\s+", " ", clean).strip(), removed


def pack_context(chunks: list[dict[str, Any]], budget_tokens: int) -> list[dict[str, Any]]:
    """Greedy pack by score within a token budget; truncate the last chunk if it doesn't fit.

    Chunk text is wrapped in delimiters by the prompt builder so the model treats it as data.
    """
    packed, used = [], 0
    for c in sorted(chunks, key=lambda c: -c["score"]):
        cost = estimate_tokens(c["text"])
        if used + cost <= budget_tokens:
            packed.append(c)
            used += cost
        else:
            remaining = budget_tokens - used
            if remaining >= 20:  # worth including a truncated chunk
                packed.append(
                    {
                        **c,
                        "text": c["text"][: remaining * 4].rsplit(" ", 1)[0] + " …",
                        "truncated": True,
                    }
                )
            break
    return packed


CITATION_RE = re.compile(r"\[([A-Z]+-[A-Z]+-\d+)\]")


def groundedness(answer: str, context: list[dict[str, Any]], min_overlap: float = 0.35) -> dict:
    """Every sentence must cite a packed chunk and lexically overlap the chunk it cites.

    A cheap, deterministic check. In production, pair it with an NLI model or LLM judge.
    """
    by_id = {c["id"]: set(tokens(c["text"])) for c in context}
    problems: list[str] = []
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|(?<=\])\s+", answer) if s.strip()]
    cited: list[str] = []
    for s in sentences:
        ids = CITATION_RE.findall(s)
        words = set(tokens(CITATION_RE.sub("", s)))
        if not ids:
            if len(words) > 2:
                problems.append(f"uncited sentence: {s[:60]!r}")
            continue
        for i in ids:
            if i not in by_id:
                problems.append(f"citation {i} not in retrieved context")
                continue
            cited.append(i)
            overlap = len(words & by_id[i]) / max(1, len(words))
            if overlap < min_overlap:
                problems.append(f"sentence not supported by {i} (overlap {overlap:.2f})")
    if not cited:
        problems.append("no valid citations")
    return {"grounded": not problems, "problems": problems, "citations": sorted(set(cited))}
