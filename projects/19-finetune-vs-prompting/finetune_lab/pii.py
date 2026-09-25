"""PII scrubbing for training data and for text entering the serving graph.

Borrower PII must never be written into a fine-tuning file: uploaded training data leaves
the loan system, is retained by the training service and can be memorised by the weights.
Structured identifiers use the shared sanitizer's patterns plus account numbers and street
addresses; names are redacted when a label anchors them ("Borrower:", "Named insured").
In production this would be Azure AI Language PII detection or Presidio (NER) in front of
the same placeholder scheme.
"""

from __future__ import annotations

import re
from collections import Counter

from shared.context.sanitize import PII_PATTERNS

_OCR_CLASS = {"i": "[il1]", "l": "[l1i]", "o": "[o0]", "e": "[ec]", "s": "[s5]"}
_ANCHORS = (
    "co-borrower",
    "borrower",
    "named insured",
    "proposed insured",
    "insured",
    "donor",
    "employee",
    "taxpayer",
    "applicant",
    "account holder",
)


def _ocr_tolerant(word: str) -> str:
    """'insured' -> '[il1]n[s5]ur[ec]d': anchors still match after OCR look-alike swaps."""
    return "".join(_OCR_CLASS.get(ch, re.escape(ch)) for ch in word).replace("rn", "(?:rn|m)")


_NAME_ANCHOR = "(?i:" + "|".join(_ocr_tolerant(a) for a in _ANCHORS) + ")"
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(PII_PATTERNS["EMAIL"])),
    ("SSN", re.compile(r"\b[\dlO]{3}-[\dlO]{2}-[\dlO]{4}\b")),
    ("ACCOUNT", re.compile(r"\b\d{8,17}\b")),
    ("PHONE", re.compile(PII_PATTERNS["PHONE"])),
    ("PHONE", re.compile(r"(?:\(\d{3}\)|\b\d{3})[\s.-]?\d{3}[\s.-]\d{4}\b")),
    (
        "ADDRESS",
        re.compile(
            r"\b\d{2,5} [A-Z][\w'-]+ (?:St|Ave|Rd|Ln|Dr|Blvd|Street|Avenue|Road|Lane|Drive)\b"
        ),
    ),
    ("NAME", re.compile(rf"({_NAME_ANCHOR}\s*:?\s*)[A-Z][\w'-]+ [A-Z][\w'-]+")),
]


def scrub(text: str) -> tuple[str, Counter[str]]:
    """Replace PII with typed placeholders (``[SSN]``, ``[NAME]`` ...). Returns counts only;
    the original values are never returned, logged or stored."""
    counts: Counter[str] = Counter()
    out = text
    for label, pat in PATTERNS:

        def _sub(m: re.Match[str], label: str = label) -> str:
            counts[label] += 1
            lead = m.group(1) if label == "NAME" else ""
            return f"{lead}[{label}]"

        out = pat.sub(_sub, out)
    return out, counts


def contains_pii(text: str) -> bool:
    return any(pat.search(text) for _, pat in PATTERNS)
