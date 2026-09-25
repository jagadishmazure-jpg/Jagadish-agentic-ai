"""Critic: deterministic checks on the drafted reply before anything reaches the customer."""

from __future__ import annotations

import re
from typing import Any

from shared.context import looks_like_injection

_MONEY_MOVED = re.compile(
    r"\b(?:has|have|was|were) been (?:refunded|issued|processed|sent)\b"
    r"|\bon its way\b|\brefund (?:is|was) complete\b",
    re.I,
)
_INTERNAL = re.compile(r"\b(?:fraud|abuse|risk flag|under review|CARE-FRAUD)\b", re.I)


def check(draft: str, facts: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    if _MONEY_MOVED.search(draft):
        issues.append("claims money moved before the payment provider confirmed (CARE-COMMS-1)")
    if _INTERNAL.search(draft):
        issues.append("leaks internal risk/fraud information")
    if looks_like_injection(draft):
        issues.append("contains instruction-like text")
    p = facts.get("proposal")
    if p:
        if p.get("policy_id") and f"[{p['policy_id']}]" not in draft:
            issues.append(f"missing citation [{p['policy_id']}]")
        if p["eligible"] and f"${p['amount']:.2f}" not in draft:
            issues.append(f"amount must be stated exactly as ${p['amount']:.2f}")
        for m in re.findall(r"\$(\d+(?:\.\d{2})?)", draft):
            if abs(float(m) - p["amount"]) > 0.005:
                issues.append(f"mentions ${m}, which is not the approved amount")
    return issues
