"""Mock collections systems of record: accounts, contact history, payment plans, messaging."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from collections_agent.audit import AuditLog
from collections_agent.registry import ToolRegistry

DEFAULT_NOW = datetime(2026, 9, 25, 16, 0, tzinfo=UTC)  # 11:00 in America/Chicago


@dataclass
class Systems:
    accounts: dict[str, dict[str, Any]]
    history: dict[str, list[dict[str, Any]]]
    plans: dict[str, dict[str, Any]] = field(default_factory=dict)
    outbox: list[dict[str, Any]] = field(default_factory=list)
    now: datetime = DEFAULT_NOW
    audit: AuditLog = field(default_factory=AuditLog)
    registry: ToolRegistry | None = None

    def clock(self) -> str:
        return self.now.isoformat()

    # --- read tools ---------------------------------------------------------------------
    def get_account(self, account_id: str) -> dict[str, Any]:
        if account_id not in self.accounts:
            raise KeyError(f"unknown account {account_id}")
        return dict(self.accounts[account_id])

    def get_contact_history(self, account_id: str) -> list[dict[str, Any]]:
        return list(self.history.get(account_id, []))

    # --- propose (no side effects on the ledger) ----------------------------------------
    def quote_plan(self, account_id: str, months: int, discount_pct: float) -> dict[str, Any]:
        bal = self.accounts[account_id]["balance"]
        total = round(bal * (1 - discount_pct / 100), 2)
        return {
            "account_id": account_id,
            "months": months,
            "discount_pct": discount_pct,
            "total": total,
            "installment": round(total / months, 2),
        }

    # --- write tools ---------------------------------------------------------------------
    def create_payment_plan(
        self, account_id: str, plan: dict[str, Any], approved_by: str, idempotency_key: str
    ) -> dict[str, Any]:
        if idempotency_key in self.plans:
            return {**self.plans[idempotency_key], "duplicate": True}
        rec = {"plan_id": f"PLAN-{len(self.plans) + 1:04d}", **plan, "approved_by": approved_by}
        self.plans[idempotency_key] = rec
        return rec

    def send_message(self, account_id: str, channel: str, body: str) -> dict[str, Any]:
        msg = {
            "message_id": f"MSG-{len(self.outbox) + 1:04d}",
            "account_id": account_id,
            "channel": channel,
            "body": body,
            "sent_at": self.clock(),
        }
        self.outbox.append(msg)
        self.history.setdefault(account_id, []).append(
            {"ts": self.clock(), "channel": channel, "direction": "outbound"}
        )
        return msg


def _attempts(n: int, now: datetime) -> list[dict[str, Any]]:
    return [
        {
            "ts": (now - timedelta(hours=20 * i + 1)).isoformat(),
            "channel": "phone",
            "direction": "outbound",
        }
        for i in range(n)
    ]


def seed_systems(now: datetime = DEFAULT_NOW) -> Systems:
    base = {
        "currency": "USD",
        "timezone": "America/Chicago",
        "channel": "email",
        "hardship": None,
        "cease_and_desist": False,
        "disputed": False,
    }
    accounts = {
        "A-1001": {
            **base,
            "account_id": "A-1001",
            "name": "Maria Lopez",
            "email": "maria.lopez@example.com",
            "phone": "+1 312 555 0147",
            "account_number": "ACCT-004417755",
            "balance": 1200.0,
            "days_past_due": 75,
        },
        "A-1002": {
            **base,
            "account_id": "A-1002",
            "name": "Dev Patel",
            "email": "dev.p@example.com",
            "phone": "+1 415 555 0199",
            "account_number": "ACCT-009912340",
            "balance": 860.0,
            "days_past_due": 40,
            "hardship": "medical",
        },
        "A-1003": {
            **base,
            "account_id": "A-1003",
            "name": "Sam Carter",
            "email": "sam.c@example.com",
            "phone": "+1 646 555 0101",
            "account_number": "ACCT-001234567",
            "balance": 450.0,
            "days_past_due": 120,
            "cease_and_desist": True,
            "timezone": "America/New_York",
        },
        "A-1004": {
            **base,
            "account_id": "A-1004",
            "name": "Lee Wong",
            "email": "lee.w@example.com",
            "phone": "+1 206 555 0133",
            "account_number": "ACCT-007654321",
            "balance": 2300.0,
            "days_past_due": 60,
            "timezone": "America/Los_Angeles",
        },
        "A-1005": {
            **base,
            "account_id": "A-1005",
            "name": "Ana Silva",
            "email": "ana.s@example.com",
            "phone": "+1 305 555 0188",
            "account_number": "ACCT-005551234",
            "balance": 310.0,
            "days_past_due": 35,
            "disputed": True,
            "timezone": "America/New_York",
        },
    }
    history = {"A-1001": _attempts(2, now), "A-1004": _attempts(7, now)}
    s = Systems(accounts=accounts, history=history, now=now)
    reg = ToolRegistry(s.audit, s.clock)
    reg.register("get_account", "accounts:read", s.get_account)
    reg.register("get_contact_history", "history:read", s.get_contact_history)
    reg.register("quote_plan", "plans:propose", s.quote_plan)
    reg.register("create_payment_plan", "plans:write", s.create_payment_plan, writes=True)
    reg.register("send_message", "messages:send", s.send_message, writes=True)
    s.registry = reg
    return s
