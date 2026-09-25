"""Receivables CRM + payments ledger behind MCP, one ToolGateway per managed identity.

The scoped registry (``registry.py``) still decides *which identity may call which tool*
(and audits denials); the call itself now crosses an MCP boundary through that identity's
gateway, which enforces its own allowlist (defence in depth), validates payloads, retries
transient errors and sanitises returned text.
"""

from __future__ import annotations

import hashlib
from typing import Any

from pydantic import BaseModel, ConfigDict

from shared.resilience import Backoff
from shared.tools import ToolGateway, connect_backends

# registry tool name -> (MCP server, MCP tool, is_write)
ROUTES: dict[str, tuple[str, str, bool]] = {
    "get_account": ("crm", "get_account", False),
    "get_contact_history": ("crm", "get_contact_history", False),
    "quote_plan": ("payments", "quote_payment_plan", False),
    "create_payment_plan": ("payments", "create_payment_plan", True),
    "send_message": ("crm", "send_customer_message", True),
}
# managed identity per registry identity (separate credentials in production)
MANAGED = {
    "collections-reader": "mi-collections-reader",
    "plan-proposer": "mi-plan-proposer",
    "plan-writer": "mi-plan-writer",
    "outreach-sender": "mi-outreach-sender",
}


class Account(BaseModel):
    """Contract for crm.get_account payloads (tool output is untrusted)."""

    model_config = ConfigDict(extra="allow")
    account_id: str
    name: str
    balance: float
    days_past_due: int
    timezone: str
    channel: str


class CrmBackend:
    def __init__(self, s: Any):
        self.s = s

    def get_account(self, account_id: str) -> dict[str, Any]:
        return self.s.get_account(account_id)

    def get_contact_history(self, account_id: str) -> list[dict[str, Any]]:
        return self.s.get_contact_history(account_id)

    def send_customer_message(self, account_id: str, channel: str, body: str) -> dict[str, Any]:
        return self.s.send_message(account_id, channel, body)


class PaymentsBackend:
    def __init__(self, s: Any):
        self.s = s

    def quote_payment_plan(self, account_id: str, months: int, discount_pct: float) -> dict:
        return self.s.quote_plan(account_id, months, discount_pct)

    def create_payment_plan(
        self, account_id: str, plan: dict[str, Any], approved_by: str, key: str
    ) -> dict[str, Any]:
        return self.s.create_payment_plan(account_id, plan, approved_by, key)


def build_gateways(s: Any, scopes_by_identity: dict[str, set[str]], tool_scopes: dict[str, str]):
    """One gateway per identity; its allowlist is derived from the identity's scopes."""
    conns = connect_backends({"crm": CrmBackend(s), "payments": PaymentsBackend(s)})
    out: dict[str, ToolGateway] = {}
    for identity, scopes in scopes_by_identity.items():
        allow = {
            f"{ROUTES[name][0]}.{ROUTES[name][1]}"
            for name, scope in tool_scopes.items()
            if scope in scopes and name in ROUTES
        }
        out[identity] = ToolGateway(
            identity,
            MANAGED[identity],
            conns,
            allow,
            schemas={"crm.get_account": Account},
            error_types={"KeyError": KeyError},
            retry=Backoff(attempts=2, base_s=0.1),
            timeout_s=5.0,
        )
    return out


def write_args(name: str, kwargs: dict[str, Any]) -> dict[str, Any]:
    """Writes go out committed (dry_run=False) with an idempotency key."""
    if name == "send_message" and "idempotency_key" not in kwargs:
        digest = hashlib.sha256(kwargs["body"].encode()).hexdigest()[:12]
        kwargs = {**kwargs, "idempotency_key": f"msg:{kwargs['account_id']}:{digest}"}
    return {**kwargs, "dry_run": False}
