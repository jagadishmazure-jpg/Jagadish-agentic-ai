"""Control-plane HTTP surface (FastAPI): the registry API plus every peer's A2A endpoint.

    GET  /registry/agents                   agent cards (control-plane view, live status)
    POST /registry/agents                   register (starts in dev)          [admin]
    POST /registry/agents/{name}/promote    eval-score gate -> prod          [admin]
    POST /registry/agents/{name}/kill       kill switch (reason required)    [admin]
    POST /registry/agents/{name}/revive                                        [admin]
    GET  /registry/audit                    allow/deny decisions with traceparent
    /agents/{name}/.well-known/agent.json   A2A agent card
    POST /agents/{name}/                    A2A JSON-RPC (message/send, tasks/get)

Run: ``uvicorn control_plane.api:app --factory``
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from control_plane.agents import Network, build_network
from control_plane.registry import AgentRecord, RegistryError

ADMIN_TOKENS = {"tok-platform-admin"}  # stub: Entra ID app role in production


def admin(x_admin_token: str = Header("")) -> None:
    if x_admin_token not in ADMIN_TOKENS:
        raise HTTPException(403, "platform admin required")


Admin = Annotated[None, Depends(admin)]


class KillIn(BaseModel):
    reason: str


def create_app(net: Network | None = None) -> FastAPI:
    net = net or build_network()
    reg = net.cp.registry
    app = FastAPI(title="agent-control-plane")
    app.state.network = net

    def rec(name: str) -> AgentRecord:
        r = reg.get(name)
        if r is None:
            raise HTTPException(404, f"{name} not registered")
        return r

    @app.get("/registry/agents")
    def list_agents() -> list[dict[str, Any]]:
        return [r.model_dump() | {"side_effect": r.side_effect} for r in reg.all()]

    @app.post("/registry/agents", status_code=201)
    def register(record: AgentRecord, _: Admin) -> dict[str, Any]:
        try:
            return reg.register(record).model_dump()
        except RegistryError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.post("/registry/agents/{name}/promote")
    def promote(name: str, _: Admin) -> dict[str, Any]:
        rec(name)
        try:
            return reg.promote(name).model_dump()
        except RegistryError as exc:
            raise HTTPException(409, str(exc)) from exc

    @app.post("/registry/agents/{name}/kill")
    def kill(name: str, body: KillIn, _: Admin) -> dict[str, str]:
        rec(name)
        reg.kill(name, body.reason)
        return {"agent": name, "status": "disabled"}

    @app.post("/registry/agents/{name}/revive")
    def revive(name: str, _: Admin) -> dict[str, str]:
        rec(name)
        reg.revive(name)
        return {"agent": name, "status": "enabled"}

    @app.get("/registry/audit")
    def audit() -> list[dict[str, str]]:
        return net.cp.audit

    for name, peer in net.apps.items():
        app.mount(f"/agents/{name}", peer)
    return app


app = create_app
