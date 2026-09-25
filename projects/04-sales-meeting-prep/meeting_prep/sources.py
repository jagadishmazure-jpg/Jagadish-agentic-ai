"""Mock research sources: CRM history, news, open deals, support tickets.

Each fetcher returns a list of items with stable source IDs (``CRM-2``, ``NEWS-1``...) so the
brief can cite them. Failures and latency are injectable per source for tests/demos.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

Item = dict[str, Any]

CRM = {
    "ACME": [
        {
            "id": "CRM-1",
            "date": "2026-08-12",
            "type": "QBR",
            "note": "Exec sponsor Dana Ruiz (VP Ops) happy with rollout; wants SSO for all teams.",
        },
        {
            "id": "CRM-2",
            "date": "2026-09-03",
            "type": "call",
            "note": "Procurement asked about multi-year pricing; budget cycle closes Oct 31.",
        },
        {
            "id": "CRM-3",
            "date": "2026-09-18",
            "type": "email",
            "note": "Champion Raj Patel flagged competitor Globex pitching their analytics team.",
        },
    ],
}
NEWS = {
    "ACME": [
        {
            "id": "NEWS-1",
            "date": "2026-09-20",
            "headline": "Acme Corp opens new EU distribution hub in Rotterdam",
            "url": "https://news.example.com/acme-eu",
        },
        {
            "id": "NEWS-2",
            "date": "2026-09-10",
            "headline": "Acme Corp names Lena Ortiz as CIO",
            "url": "https://news.example.com/acme-cio",
        },
    ],
}
DEALS = {
    "ACME": [
        {
            "id": "DEAL-1",
            "name": "Analytics add-on (EU)",
            "amount": 180000,
            "stage": "Proposal",
            "close": "2026-10-31",
        },
        {
            "id": "DEAL-2",
            "name": "3-year renewal",
            "amount": 420000,
            "stage": "Negotiation",
            "close": "2026-12-15",
        },
    ],
}
TICKETS = {
    "ACME": [
        {
            "id": "SUP-1",
            "priority": "P1",
            "status": "open",
            "subject": "SSO login failures for EU users",
            "age_days": 6,
        },
        {
            "id": "SUP-2",
            "priority": "P3",
            "status": "resolved",
            "subject": "Export to CSV slow",
            "age_days": 20,
        },
    ],
}


@dataclass
class Sources:
    failures: dict[str, BaseException] = field(default_factory=dict)  # source -> exception
    transient: dict[str, int] = field(default_factory=dict)  # source -> failures before success
    latency_s: float = 0.0
    calls: dict[str, int] = field(default_factory=dict)

    def _fetch(self, name: str, data: dict[str, list[Item]], account: str) -> list[Item]:
        self.calls[name] = self.calls.get(name, 0) + 1
        if self.latency_s:
            time.sleep(self.latency_s)
        if name in self.failures:
            raise self.failures[name]
        if self.transient.get(name, 0) > 0:
            self.transient[name] -= 1
            raise TimeoutError(f"{name} timed out")
        return [dict(i) for i in data.get(account, [])]

    def fetchers(self) -> dict[str, Callable[[str], list[Item]]]:
        return {
            "crm": lambda a: self._fetch("crm", CRM, a),
            "news": lambda a: self._fetch("news", NEWS, a),
            "deals": lambda a: self._fetch("deals", DEALS, a),
            "support": lambda a: self._fetch("support", TICKETS, a),
        }


def seed_sources(**kwargs: Any) -> Sources:
    return Sources(**kwargs)
