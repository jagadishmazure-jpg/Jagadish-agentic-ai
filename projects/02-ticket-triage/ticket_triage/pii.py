"""Regex + checksum PII redaction. Runs before any text reaches an LLM."""

from __future__ import annotations

import re
from collections import Counter

PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("PHONE", re.compile(r"(?<!\d)(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]?\d{3}[ .-]?\d{4}\b")),
    ("IP", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
]


def luhn_ok(number: str) -> bool:
    digits = [int(d) for d in re.sub(r"\D", "", number)][::-1]
    total = sum(
        d if i % 2 == 0 else (d * 2 - 9 if d * 2 > 9 else d * 2) for i, d in enumerate(digits)
    )
    return len(digits) >= 13 and total % 10 == 0


def redact(text: str) -> tuple[str, dict[str, str], Counter]:
    """Return (redacted_text, vault{placeholder: original}, counts). The vault never
    leaves the trusted boundary (it is not sent to the model or written to logs)."""
    vault: dict[str, str] = {}
    counts: Counter = Counter()

    for kind, pattern in PATTERNS:

        def repl(m: re.Match[str], kind: str = kind) -> str:
            value = m.group(0)
            if kind == "CARD" and not luhn_ok(value):
                return value  # long number that isn't a card (order id etc.)
            counts[kind] += 1
            key = f"[{kind}_{counts[kind]}]"
            vault[key] = value
            return key

        text = pattern.sub(repl, text)
    return text, vault, counts
