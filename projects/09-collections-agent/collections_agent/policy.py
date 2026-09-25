"""Deterministic governance policies: hardship, contact rules, plan limits, message content.

Loosely modelled on FDCPA / Reg F style rules (contact hours 08:00-21:00 debtor local time,
7 attempts in 7 days cap, cease-and-desist, disputes) - illustrative, not legal advice.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

CONTACT_START_HOUR, CONTACT_END_HOUR = 8, 21
MAX_ATTEMPTS_7D = 7
MAX_MONTHS, MIN_INSTALLMENT, MAX_DISCOUNT_PCT = 12, 25.0, 10.0
DISCLOSURE = "This is a communication from a debt collector. This is an attempt to collect a debt."
BANNED_PHRASES = [
    r"\barrest",
    r"\bjail",
    r"\bpolice\b",
    r"\bcriminal",
    r"\bgarnish",
    r"\bsue you\b",
    r"\blawsuit",
    r"\bruin your credit",
    r"\bfinal warning",
    r"\btell your (employer|family)",
]


def contact_decision(
    account: dict[str, Any], history: list[dict[str, Any]], now: datetime
) -> tuple[str, list[str]]:
    """Return (decision, reasons). decision in allowed|hardship|no_contact|defer."""
    if account.get("hardship"):
        return "hardship", [f"hardship flag: {account['hardship']} - refer to hardship team"]
    if account.get("cease_and_desist"):
        return "no_contact", ["cease-and-desist on file - no further collection contact"]
    if account.get("disputed"):
        return "no_contact", ["debt disputed - contact paused until validation is sent"]
    reasons = []
    local = now.astimezone(ZoneInfo(account["timezone"]))
    if not CONTACT_START_HOUR <= local.hour < CONTACT_END_HOUR:
        reasons.append(
            f"outside allowed hours ({local:%H:%M} {account['timezone']}; "
            f"allowed {CONTACT_START_HOUR:02d}:00-{CONTACT_END_HOUR:02d}:00)"
        )
    recent = [
        h
        for h in history
        if h.get("direction") == "outbound"
        and datetime.fromisoformat(h["ts"]) > now - timedelta(days=7)
    ]
    if len(recent) >= MAX_ATTEMPTS_7D:
        reasons.append(
            f"frequency cap: {len(recent)} attempts in last 7 days (max {MAX_ATTEMPTS_7D})"
        )
    return ("defer", reasons) if reasons else ("allowed", ["within contact rules"])


def next_allowed_time(account: dict[str, Any], now: datetime) -> str:
    tz = ZoneInfo(account["timezone"])
    local = now.astimezone(tz)
    nxt = local.replace(hour=CONTACT_START_HOUR, minute=0, second=0, microsecond=0)
    if local.hour >= CONTACT_START_HOUR:
        nxt += timedelta(days=1)
    return nxt.isoformat()


def check_plan(plan: dict[str, Any], balance: float) -> tuple[dict[str, Any], list[str]]:
    """Clamp a proposed plan into policy; return (compliant_plan, violations_found)."""
    violations = []
    months = int(plan.get("months", 6))
    discount = float(plan.get("discount_pct", 0))
    if months > MAX_MONTHS:
        violations.append(f"term {months} months > max {MAX_MONTHS}")
        months = MAX_MONTHS
    if months < 1:
        violations.append("term must be >= 1 month")
        months = 1
    if discount > MAX_DISCOUNT_PCT:
        violations.append(f"discount {discount}% > max {MAX_DISCOUNT_PCT}%")
        discount = MAX_DISCOUNT_PCT
    total = round(balance * (1 - discount / 100), 2)
    while months > 1 and total / months < MIN_INSTALLMENT:
        months -= 1
    if int(plan.get("months", 6)) != months and not violations:
        violations.append(f"installment below ${MIN_INSTALLMENT:.0f} minimum - term shortened")
    return {"months": months, "discount_pct": discount}, violations


def check_message(body: str) -> list[str]:
    issues = [f"banned phrase /{p}/" for p in BANNED_PHRASES if re.search(p, body, re.I)]
    if DISCLOSURE not in body:
        issues.append("missing required debt-collector disclosure")
    return issues


def safe_template(first_name: str, plan: dict[str, Any]) -> str:
    return (
        f"Hello {first_name},\n\nWe'd like to help you resolve your balance. We can offer a "
        f"plan of {plan['months']} monthly payments of ${plan['installment']:.2f}. Reply to "
        f"this message or call us to accept or discuss other options.\n\n{DISCLOSURE}"
    )
