"""Demand/capacity peer agent behind the shared A2A contract (same contract as project 12).

Serves its agent card at ``/.well-known/agent.json`` and the ``network_whatif`` skill over
JSON-RPC. Lane demand for next week reuses project 10's forecasting logic; alternatives are
flagged ``capacity_ok`` against lane capacity. A registration/tenant guard rejects unknown
callers before any skill code runs.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, Field

from shared.a2a import A2AClient, A2ARejection, AgentCard, AgentSkill, CallContext, Skill, a2a_app

_P10 = Path(__file__).resolve().parents[2] / "10-supply-chain-multi-agent"
if str(_P10) not in sys.path:
    sys.path.append(str(_P10))
from supply_chain.tools import forecast_from_history  # noqa: E402

NAME = "capacity-agent"
CALLERS = {"exception-agent": {"northwind", "contoso"}}
LANES: dict[str, dict[str, Any]] = {
    "CHI-NYC": {
        "weekly_loads": [41, 44, 46, 45, 48, 50, 53, 55],
        "capacity": 60,
        "alternatives": [
            {"mode": "team truck", "carrier": "Ridgeline Freight", "eta_gain_h": 10},
            {"mode": "air", "carrier": "SkyBridge Air", "eta_gain_h": 20},
        ],
    },
    "DAL-ATL": {
        "weekly_loads": [30, 31, 29, 33, 35, 34, 36, 38],
        "capacity": 40,
        "alternatives": [{"mode": "team truck", "carrier": "Coastal Carriers", "eta_gain_h": 8}],
    },
    "LAX-SEA": {
        "weekly_loads": [20, 22, 21, 23, 22, 24, 25, 24],
        "capacity": 45,
        "alternatives": [{"mode": "team truck", "carrier": "Ridgeline Freight", "eta_gain_h": 9}],
    },
}


class WhatIfIn(BaseModel):
    shipment_id: str = Field(pattern=r"^SH-\d{4}$")
    lane: str = Field(pattern=r"^[A-Z]{3}-[A-Z]{3}$")
    delay_hours: float = Field(ge=0, le=240)


def card() -> AgentCard:
    return AgentCard(
        name=NAME,
        description="Lane demand forecast and capacity what-if for reroutes",
        url=f"http://{NAME}.agents.internal",
        version="1.1.0",
        skills=[
            AgentSkill(
                id="network_whatif",
                name="network_whatif",
                description="Reroute options with capacity check",
                tags=["read_only"],
            )
        ],
        metadata={
            "owner": "Jagadish Meduri",
            "side_effect": "read_only",
            "allowed_callers": sorted(CALLERS),
        },
    )


def guard(ctx: CallContext, _card: AgentCard) -> None:
    if ctx.caller not in CALLERS:
        raise A2ARejection(f"caller '{ctx.caller}' is not registered for {NAME}")
    if ctx.tenant not in CALLERS[ctx.caller]:
        raise A2ARejection(f"tenant '{ctx.tenant}' not allowed for {ctx.caller}")


def whatif(inp: WhatIfIn, ctx: CallContext) -> dict[str, Any]:
    lane = LANES.get(inp.lane)
    if lane is None:
        return {"lane": inp.lane, "options": [], "note": "unknown lane"}
    fc = forecast_from_history(lane["weekly_loads"], 1)
    load = fc["weekly"][0] / lane["capacity"]
    opts = [
        {
            **o,
            "recovers_delay": o["eta_gain_h"] >= inp.delay_hours,
            "capacity_ok": o["mode"] == "air" or load < 0.9,
        }
        for o in lane["alternatives"]
    ]
    return {
        "lane": inp.lane,
        "forecast_loads_next_week": fc["weekly"][0],
        "lane_load_pct": round(load * 100, 1),
        "method": fc["method"],
        "options": opts,
    }


def app() -> FastAPI:
    return a2a_app(card(), {"network_whatif": Skill(WhatIfIn, whatif, "whatif")}, guard=guard)


def client(caller: str | None = "exception-agent") -> A2AClient:
    return A2AClient(NAME, TestClient(app()), caller=caller)
