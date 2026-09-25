"""Peer agents behind A2A, each with its own MCP identity to its system of record.

* ``crm-agent``     customer 360 (tier, credit hold) from the CRM            - read_only
* ``sap-agent``     stock + open POs, and PO *drafts* in the SAP-like ERP     - reversible_write
* ``demand-agent``  Databricks-like demand forecast over the semantic model  - read_only
                    (reuses project 10's forecasting logic and seed data)
* ``journey-agent`` the caller (LangGraph, see ``journey.py``); registered like everyone else
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from control_plane.plane import ControlPlane
from control_plane.registry import AgentRecord, Registry
from shared.a2a import A2AClient, AgentCard, AgentSkill, CallContext, Skill, a2a_app
from shared.resilience import Backoff
from shared.tools import ToolGateway, connect_backends

# Reuse project 10's demand logic + seed ERP/sales data (sibling project, not a package dep).
_P10 = Path(__file__).resolve().parents[2] / "10-supply-chain-multi-agent"
if str(_P10) not in sys.path:
    sys.path.append(str(_P10))
from supply_chain.services import Services, seed_services  # noqa: E402
from supply_chain.tools import forecast_from_history  # noqa: E402

ACCOUNTS = {
    "ACME-B2B": {
        "customer_id": "ACME-B2B",
        "name": "Acme Industrial",
        "tenant": "northwind",
        "tier": "gold",
        "credit_hold": False,
        "notes": "Prefers consolidated shipments at month end.",
    },
    "GLOBEX-B2B": {
        "customer_id": "GLOBEX-B2B",
        "name": "Globex Retail",
        "tenant": "northwind",
        "tier": "silver",
        "credit_hold": True,
        "notes": "Invoices 60+ days overdue.",
    },
    "INITECH-B2B": {
        "customer_id": "INITECH-B2B",
        "name": "Initech",
        "tenant": "contoso",
        "tier": "gold",
        "credit_hold": False,
        "notes": "",
    },
}


# ------------------------------------------------------------------------ MCP backends
@dataclass
class CrmBackend:
    accounts: dict[str, dict[str, Any]]

    def get_account(self, account_id: str) -> dict[str, Any]:
        return dict(self.accounts[account_id])


@dataclass
class ErpBackend:
    s: Services

    def get_stock(self, sku: str) -> dict[str, Any]:
        return self.s.erp.stock(sku) or {
            "on_hand": 0,
            "safety_stock": 0,
            "reorder_point": 0,
            "lead_time_days": 0,
        }

    def get_open_purchase_orders(self, sku: str) -> list[dict[str, Any]]:
        return self.s.erp.open_pos(sku)

    def create_po_draft(self, po: dict[str, Any]) -> dict[str, Any]:
        return self.s.erp.create_draft(**po)


@dataclass
class AnalyticsBackend:
    s: Services

    def get_measure(self, measure: str, entity: str, grain: str) -> dict[str, Any]:
        if measure != "weekly_units":
            raise KeyError(f"no certified measure {measure}")
        return {"measure": measure, "entity": entity, "values": self.s.sales.history(entity)}


# ------------------------------------------------------------------------ skill contracts
class CustomerIn(BaseModel):
    customer_id: str = Field(pattern=r"^[A-Z0-9-]+$")


class StockIn(BaseModel):
    sku: str = Field(pattern=r"^SKU-\d{3}$")


class DraftIn(BaseModel):
    sku: str = Field(pattern=r"^SKU-\d{3}$")
    qty: int = Field(gt=0, le=10_000)
    reason: str = Field(min_length=5)
    idempotency_key: str = Field(min_length=8)


class ForecastIn(BaseModel):
    sku: str = Field(pattern=r"^SKU-\d{3}$")
    weeks: int = Field(ge=1, le=12)


# ------------------------------------------------------------------------ records
def records() -> list[AgentRecord]:
    common = {"owner": "Jagadish Meduri", "tenants": ["northwind", "contoso"]}
    return [
        AgentRecord(
            name="journey-agent",
            version="1.2.0",
            purpose="B2B order-promise journey orchestrator for account managers",
            skills={"promise": "reversible_write"},
            models=["gpt-4o-mini", "gpt-4o-mini-fallback"],
            allowed_callers=[],
            eval_scores={"task_success": 1.0, "policy_violation_rate": 0.0},
            **common,
        ),
        AgentRecord(
            name="crm-agent",
            version="2.0.1",
            purpose="Customer 360: tier, credit hold and account notes from the CRM",
            skills={"get_customer_360": "read_only"},
            tools=["crm.get_account"],
            allowed_callers=["journey-agent"],
            eval_scores={"task_success": 0.97, "policy_violation_rate": 0.0},
            **common,
        ),
        AgentRecord(
            name="sap-agent",
            version="3.1.0",
            purpose="Stock, open purchase orders and PO drafts in the SAP-like ERP",
            skills={"get_stock": "read_only", "create_po_draft": "reversible_write"},
            tools=["erp.get_stock", "erp.get_open_purchase_orders", "erp.create_po_draft"],
            allowed_callers=["journey-agent", "marketing-agent"],
            eval_scores={"task_success": 0.96, "policy_violation_rate": 0.0},
            **common,
        ),
        AgentRecord(
            name="demand-agent",
            version="1.4.0",
            purpose="Databricks-like demand forecast over the certified weekly_units measure",
            skills={"forecast": "read_only"},
            tools=["analytics.get_measure"],
            allowed_callers=["journey-agent"],
            eval_scores={"task_success": 0.91, "policy_violation_rate": 0.0},
            **common,
        ),
        AgentRecord(
            name="marketing-agent",
            version="0.3.0",
            purpose="Campaign assistant that wants stock numbers for promotions",
            skills={"campaign": "read_only"},
            eval_scores={"task_success": 0.85, "policy_violation_rate": 0.0},
            **common,
        ),
    ]


def default_policy(cp: ControlPlane) -> None:
    cp.allow("*", "journey-agent", "crm-agent", "get_customer_360")
    cp.allow("*", "journey-agent", "demand-agent", "forecast")
    cp.allow("*", "journey-agent", "sap-agent", "get_stock")
    cp.allow("northwind", "journey-agent", "sap-agent", "create_po_draft")  # tenant-scoped write
    cp.allow("*", "marketing-agent", "sap-agent", "get_stock")  # read only, no drafts


def card_for(rec: AgentRecord, descriptions: dict[str, str]) -> AgentCard:
    return AgentCard(
        name=rec.name,
        description=rec.purpose,
        url=f"http://{rec.name}.agents.internal",
        version=rec.version,
        skills=[
            AgentSkill(id=k, name=k, description=descriptions.get(k, k), tags=[v])
            for k, v in rec.skills.items()
        ],
        metadata={
            "owner": rec.owner,
            "side_effect": rec.side_effect,
            "side_effects": dict(rec.skills),
            "allowed_callers": rec.allowed_callers,
            "tenants": rec.tenants,
            "stage": rec.stage,
            "budgets": rec.budgets.model_dump(),
            "eval_scores": rec.eval_scores,
        },
    )


# ------------------------------------------------------------------------ network
@dataclass
class Network:
    """The agent mesh: control plane + one A2A app per peer + MCP gateways per identity."""

    cp: ControlPlane
    services: Services
    accounts: dict[str, dict[str, Any]]
    apps: dict[str, FastAPI] = field(default_factory=dict)
    gateways: dict[str, ToolGateway] = field(default_factory=dict)

    def client(self, callee: str, caller: str = "journey-agent") -> A2AClient:
        return A2AClient(callee, TestClient(self.apps[callee]), caller=caller)


def build_network(promote: bool = True) -> Network:
    reg = Registry()
    for r in records():
        reg.register(r)
    cp = ControlPlane(reg)
    default_policy(cp)
    if promote:
        for r in records():
            reg.promote(r.name)
    s = seed_services()
    accounts = {k: dict(v) for k, v in ACCOUNTS.items()}
    conns = connect_backends(
        {"crm": CrmBackend(accounts), "erp": ErpBackend(s), "analytics": AnalyticsBackend(s)}
    )
    net = Network(cp, s, accounts)

    def gw(agent: str, allow: set[str]) -> ToolGateway:
        g = ToolGateway(
            agent,
            f"mi-{agent}",
            conns,
            allow,
            error_types={"KeyError": KeyError},
            retry=Backoff(attempts=2, base_s=0.05),
            timeout_s=5.0,
        )
        net.gateways[agent] = g
        return g

    crm = gw("crm-agent", {"crm.get_account"})
    sap = gw("sap-agent", {"erp.get_stock", "erp.get_open_purchase_orders", "erp.create_po_draft"})
    dem = gw("demand-agent", {"analytics.get_measure"})

    def customer_360(inp: CustomerIn, ctx: CallContext) -> dict[str, Any]:
        try:
            a = crm.call("crm", "get_account", account_id=inp.customer_id)
        except KeyError:
            return {"found": False}
        if a["tenant"] != ctx.tenant:  # tenant isolation inside the agent, too
            return {"found": False}
        return {
            "found": True,
            **{k: a[k] for k in ("customer_id", "name", "tier", "credit_hold", "notes")},
        }

    def get_stock(inp: StockIn, ctx: CallContext) -> dict[str, Any]:
        st = sap.call("erp", "get_stock", sku=inp.sku)
        pos = sap.call("erp", "get_open_purchase_orders", sku=inp.sku)
        return {
            "sku": inp.sku,
            "on_hand": st["on_hand"],
            "safety_stock": st["safety_stock"],
            "open_po_qty": sum(p["qty"] for p in pos),
        }

    def create_po_draft(inp: DraftIn, ctx: CallContext) -> dict[str, Any]:
        po = {
            "sku": inp.sku,
            "qty": inp.qty,
            "supplier": "TBD (buyer sources)",
            "unit_price": 0.0,
            "total": 0.0,
            "reason": inp.reason,
            "tenant": ctx.tenant,
        }
        return sap.call(
            "erp", "create_po_draft", po=po, idempotency_key=inp.idempotency_key, dry_run=False
        )

    def forecast(inp: ForecastIn, ctx: CallContext) -> dict[str, Any]:
        h = dem.call("analytics", "get_measure", measure="weekly_units", entity=inp.sku)["values"]
        return {"sku": inp.sku, "weeks": inp.weeks, **forecast_from_history(h, inp.weeks)}

    skills = {
        "crm-agent": {"get_customer_360": Skill(CustomerIn, customer_360, "customer_360")},
        "sap-agent": {
            "get_stock": Skill(StockIn, get_stock, "stock"),
            "create_po_draft": Skill(DraftIn, create_po_draft, "po_draft"),
        },
        "demand-agent": {"forecast": Skill(ForecastIn, forecast, "forecast")},
    }
    for name, sk in skills.items():
        rec = reg.get(name)
        assert rec is not None
        net.apps[name] = a2a_app(card_for(rec, {}), sk, guard=cp.guard_for(name))
    return net
