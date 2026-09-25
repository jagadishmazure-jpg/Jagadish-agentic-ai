"""Tamper-evident audit log (SHA-256 hash chain) with PII masking on write."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

GENESIS = "0" * 64
_EMAIL = re.compile(r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+)")
_PHONE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
_ACCOUNT = re.compile(r"\b(?:ACCT|IBAN|CARD)[- ]?\d{4,}(\d{4})\b")
HASHED_KEYS = {"body"}
SENSITIVE_KEYS = {"name", "email", "phone", "address", "bank_account", "ssn", "dob"}


def mask_text(text: str) -> str:
    text = _EMAIL.sub(r"\1***@\2", text)
    text = _ACCOUNT.sub(r"****\1", text)
    return _PHONE.sub(lambda m: "***-***-" + re.sub(r"\D", "", m.group(0))[-4:], text)


def mask(value: Any, key: str = "") -> Any:
    """Recursively mask PII: sensitive keys are redacted, free text is pattern-masked."""
    if isinstance(value, dict):
        return {k: mask(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [mask(v) for v in value]
    if key in HASHED_KEYS and value:  # keep verifiable evidence without storing content
        return "sha256:" + hashlib.sha256(str(value).encode()).hexdigest()[:16]
    if key in SENSITIVE_KEYS and value:
        s = str(value)
        return s[0] + "***" if key == "name" else "[REDACTED]"
    return mask_text(value) if isinstance(value, str) else value


def _digest(prev: str, body: dict[str, Any]) -> str:
    return hashlib.sha256((prev + json.dumps(body, sort_keys=True)).encode()).hexdigest()


@dataclass
class AuditLog:
    entries: list[dict[str, Any]] = field(default_factory=list)

    def record(self, actor: str, action: str, ts: str, **details: Any) -> dict[str, Any]:
        prev = self.entries[-1]["hash"] if self.entries else GENESIS
        body = {
            "seq": len(self.entries) + 1,
            "ts": ts,
            "actor": actor,
            "action": action,
            "details": mask(details),
            "prev_hash": prev,
        }
        entry = {**body, "hash": _digest(prev, body)}
        self.entries.append(entry)
        return entry

    def verify(self) -> tuple[bool, int | None]:
        """Recompute the chain. Returns (ok, first_bad_seq)."""
        prev = GENESIS
        for e in self.entries:
            body = {k: e[k] for k in ("seq", "ts", "actor", "action", "details", "prev_hash")}
            if e["prev_hash"] != prev or _digest(prev, body) != e["hash"]:
                return False, e["seq"]
            prev = e["hash"]
        return True, None

    def actions(self) -> list[str]:
        return [e["action"] for e in self.entries]
