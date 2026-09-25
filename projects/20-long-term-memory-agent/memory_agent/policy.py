"""Memory write policy: what may be saved, in what form, and what wins on conflict.

Checked in order for every candidate the extractor proposes:

1. **Consent.** Without memory consent nothing is written to long-term memory (the thread
   checkpoint still holds the current conversation).
2. **Poisoning / injection.** Text that reads like instructions to the assistant ("ignore
   previous instructions", "always approve", "waive my fees", "skip verification") is
   rejected and flagged. Memory is data, never a place to smuggle policy.
3. **Procedural allowlist.** Preferences may only set presentation keys (name, channel,
   language, answer style). Unknown keys are rejected.
4. **Sensitive data.** Credentials (PIN, password, full card or SSN) are never stored: the
   candidate is rejected. Other identifiers (account numbers, emails, phones) are redacted
   before the value is written.
5. **Confidence.** Candidates below ``MIN_CONFIDENCE`` (hedged or inferred) are skipped.
6. **Conflicts.** Same key: an inferred value never overrides a user-stated one; a newer
   user-stated value supersedes the old one, which moves to bounded ``history``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from memory_agent.schema import KEYS, MIN_CONFIDENCE, PREFERENCE_ALLOWLIST, Candidate, MemoryRecord
from shared.context import looks_like_injection

Action = Literal["save", "update", "skip", "reject"]

POLICY_OVERRIDE = re.compile(
    r"\b(?:always|automatically|never)\s+(?:approve|waive|allow|skip|bypass|refund)|"
    r"\bwaive(?:d)?\b.*\bfees?\b|\bfees?\b.*\bwaived?\b|\bno (?:transfer |daily )?limits?\b|"
    r"\b(?:skip|bypass|disable)\s+(?:the\s+)?(?:verification|kyc|2fa|otp|security)|"
    r"\b(?:admin|administrator|root)\b",
    re.I,
)
CREDENTIAL = re.compile(
    r"\b(?:pin|password|passcode|cvv|security code)\b|\b\d{3}-\d{2}-\d{4}\b|\b(?:\d[ -]?){15,16}\b",
    re.I,
)
REDACT = [
    ("ACCOUNT", re.compile(r"\b\d{8,14}\b")),
    ("EMAIL", re.compile(r"\b[\w.%+-]+@[\w.-]+\.[A-Za-z]{2,}\b")),
    ("PHONE", re.compile(r"(?:\(\d{3}\)|\b\d{3})[\s.-]?\d{3}[\s.-]\d{4}\b")),
]


@dataclass
class Decision:
    action: Action
    reason: str
    candidate: Candidate
    flagged: bool = False  # poisoning attempts are escalated for review


def redact(value: str) -> tuple[str, int]:
    n = 0
    for label, pat in REDACT:
        value, k = pat.subn(f"[{label}]", value)
        n += k
    return value, n


def decide(c: Candidate, existing: MemoryRecord | None, consent: bool) -> Decision:
    if not consent:
        return Decision("skip", "no memory consent", c)
    if looks_like_injection(c.value) or POLICY_OVERRIDE.search(c.value):
        return Decision("reject", "instruction-like content (possible memory poisoning)", c, True)
    if c.kind == "preference" and c.key not in PREFERENCE_ALLOWLIST:
        return Decision("reject", f"'{c.key}' is not an allowed preference", c, True)
    if c.kind == "profile" and c.key not in KEYS:
        return Decision("reject", f"'{c.key}' is not a known profile fact", c)
    if CREDENTIAL.search(c.value):
        return Decision("reject", "credentials / full identifiers are never stored", c)
    value, n = redact(c.value)
    c = c.model_copy(update={"value": value})
    if c.confidence < MIN_CONFIDENCE:
        return Decision("skip", f"confidence {c.confidence:.2f} < {MIN_CONFIDENCE}", c)
    if existing is None:
        return Decision("save", "new memory" + (f" ({n} identifier(s) redacted)" if n else ""), c)
    if existing.value == c.value:
        return Decision("update", "re-confirmed (refreshes recency and TTL)", c)
    if c.source == "inferred" and existing.source == "user_stated":
        return Decision("skip", "inferred value cannot override a user-stated one", c)
    return Decision("update", f"supersedes '{existing.value}'", c)
