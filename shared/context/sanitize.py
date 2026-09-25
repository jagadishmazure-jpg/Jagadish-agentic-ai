"""Sanitizer for untrusted text entering the context window (retrieved chunks, tickets,
tool observations): neutralises injected instructions and redacts secrets / PII."""

from __future__ import annotations

import re
from dataclasses import dataclass

INJECTION_PATTERNS = [
    r"ignore (?:all |any )?(?:the )?(?:previous|prior|above|earlier|preceding)?\s*"
    r"(?:instructions|rules|guidance|prompts?)",
    r"disregard (?:all |any |the )?(?:previous |prior |above )?(?:instructions|rules|policy)",
    r"forget (?:all |your |the )?(?:previous |prior )?(?:instructions|rules)",
    r"you are now\b",
    r"new (?:system )?instructions?:",
    r"\bsystem prompt\b",
    r"\b(?:system|assistant|developer)\s*:",
    r"<\s*/?\s*(?:system|script|instructions?)\b[^>]*>",
    r"\bact as (?:an? )?(?:admin|administrator|developer|system|root)\b",
    r"\b(?:reveal|print|output|exfiltrate|leak) (?:the |your )?"
    r"(?:system prompt|instructions|secrets?|api keys?|credentials?)",
    r"\bdo not (?:tell|inform) the (?:user|customer|reviewer)\b",
    r"\b(?:call|invoke|use) the \w+ tool\b",
    r"\bjailbreak\b|\bDAN mode\b|\bdeveloper mode\b",
]
_INJ = re.compile("|".join(f"(?:{p})" for p in INJECTION_PATTERNS), re.I)
_SENTENCE = re.compile(r"[^.!?\n]*(?:[.!?]|\n|$)")

SECRET_PATTERNS = [
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
    r"\bAKIA[0-9A-Z]{16}\b",
    r"\bsk-[A-Za-z0-9_-]{16,}\b",
    r"\bgh[pousr]_[A-Za-z0-9]{20,}\b",
    r"\bbearer\s+[A-Za-z0-9._~+/-]{16,}=*",
    r"\b(?:api[_-]?key|secret|password|passwd|pwd|token|connection[_ ]?string)\b"
    r"\s*[:=]\s*\S+",
]
_SECRET = re.compile("|".join(f"(?:{p})" for p in SECRET_PATTERNS), re.I)
PII_PATTERNS = {
    "EMAIL": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
    "SSN": r"\b\d{3}-\d{2}-\d{4}\b",
    "CARD": r"\b(?:\d[ -]?){13,16}\b",
    "PHONE": r"(?<![\w-])\+?\d{1,2}[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}\b",
}


@dataclass(frozen=True)
class Sanitized:
    text: str
    injections: int = 0
    secrets: int = 0
    pii: int = 0

    @property
    def flagged(self) -> bool:
        return bool(self.injections or self.secrets)


def looks_like_injection(text: str) -> bool:
    return bool(_INJ.search(text))


def sanitize(text: str, *, redact_pii: bool = True) -> Sanitized:
    injections = 0

    def _neutral(m: re.Match[str]) -> str:
        nonlocal injections
        s = m.group(0)
        if s.strip() and _INJ.search(s):
            injections += 1
            return "[removed: suspected injected instruction] "
        return s

    out = _SENTENCE.sub(_neutral, text)
    out, secrets = _SECRET.subn("[REDACTED:SECRET]", out)
    pii = 0
    if redact_pii:
        for label, pat in PII_PATTERNS.items():
            out, n = re.subn(pat, f"[REDACTED:{label}]", out)
            pii += n
    return Sanitized(out, injections, secrets, pii)
