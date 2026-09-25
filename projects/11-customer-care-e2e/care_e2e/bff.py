"""Experience plane: FastAPI backend-for-frontend in front of the care graph.

* auth stub: bearer token -> claims (customer id, email, tenant, allowed channels, roles).
  The graph gets identity from claims, never from the request body.
* channel claim: the path channel must be one the token was issued for.
* tenant check: ``X-Tenant-Id`` must match the token's tenant.
* rate limit: token bucket per (tenant, channel), returns 429 with Retry-After.
* ``POST /v1/channels/{channel}/messages``         one-shot JSON reply
* ``POST /v1/channels/{channel}/messages/stream``  SSE: node progress, reply chunks, done
* ``POST /v1/approvals/{thread_id}``               care-specialist decision (HITL resume)
* ``POST /v1/ops/sla-sweep``                       timer job: expire overdue approvals
"""

from __future__ import annotations

import itertools
import json
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import StreamingResponse
from langgraph.types import Command
from pydantic import BaseModel

from care_e2e.graph import build_graph, sweep_expired
from care_e2e.systems import Systems, seed_systems

TOKENS: dict[str, dict[str, Any]] = {  # auth stub (Entra ID / APIM JWT validation in prod)
    "tok-ana": {
        "sub": "C100",
        "email": "ana@example.com",
        "tenant": "acme-retail",
        "channels": ["web", "app"],
        "roles": ["customer"],
    },
    "tok-ben": {
        "sub": "C200",
        "email": "ben@example.com",
        "tenant": "acme-retail",
        "channels": ["web"],
        "roles": ["customer"],
    },
    "tok-cy": {
        "sub": "C300",
        "email": "cy@example.com",
        "tenant": "acme-retail",
        "channels": ["web"],
        "roles": ["customer"],
    },
    "tok-sam": {
        "sub": "sam.approver",
        "tenant": "acme-retail",
        "channels": ["console"],
        "roles": ["care-approver", "ops"],
    },
}
CHANNELS = ("web", "app", "email")


@dataclass
class TokenBucket:
    capacity: int
    per_seconds: float
    clock: Callable[[], float] = time.monotonic
    _state: dict[tuple[str, str], tuple[float, float]] = field(default_factory=dict)

    def allow(self, key: tuple[str, str]) -> tuple[bool, float]:
        now = self.clock()
        tokens, last = self._state.get(key, (float(self.capacity), now))
        tokens = min(self.capacity, tokens + (now - last) * self.capacity / self.per_seconds)
        if tokens < 1:
            self._state[key] = (tokens, now)
            return False, (1 - tokens) * self.per_seconds / self.capacity
        self._state[key] = (tokens - 1, now)
        return True, 0.0


class MessageIn(BaseModel):
    message: str


class DecisionIn(BaseModel):
    decision: str  # approve | deny


class SweepIn(BaseModel):
    now: datetime


def claims(authorization: str = Header(""), x_tenant_id: str = Header("")) -> dict:
    c = TOKENS.get(authorization.removeprefix("Bearer ").strip())
    if not c:
        raise HTTPException(401, "invalid token")
    if x_tenant_id != c["tenant"]:
        raise HTTPException(403, "tenant mismatch")
    return c


Claims = Annotated[dict, Depends(claims)]


def create_app(
    systems: Systems | None = None, graph: Any = None, limiter: TokenBucket | None = None
) -> FastAPI:
    s = systems or seed_systems()
    g = graph or build_graph(s)
    bucket = limiter or TokenBucket(capacity=20, per_seconds=60)
    ids = itertools.count(1)
    app = FastAPI(title="care-bff")
    app.state.systems, app.state.graph = s, g

    def admit(channel: str, c: dict) -> None:
        if channel not in CHANNELS or channel not in c["channels"]:
            raise HTTPException(403, f"token not issued for channel '{channel}'")
        ok, retry = bucket.allow((c["tenant"], channel))
        if not ok:
            raise HTTPException(429, "rate limited", headers={"Retry-After": f"{retry:.0f}"})

    def start(channel: str, body: MessageIn, c: dict) -> tuple[dict, dict]:
        n = next(ids)
        req = {
            "request_id": f"req-{n}",
            "channel": channel,
            "tenant": c["tenant"],
            "customer_id": c["sub"],
            "email": c["email"],
            "message": body.message,
        }
        cfg = {
            "configurable": {"thread_id": f"{c['tenant']}:{channel}:{n}"},
            "metadata": {"identity": c["sub"], "tenant": c["tenant"], "channel": channel},
        }
        return {"request": req}, cfg

    def view(result: dict, cfg: dict) -> dict[str, Any]:
        thread = cfg["configurable"]["thread_id"]
        if "__interrupt__" in result:
            p = result["__interrupt__"][0].value
            return {
                "thread_id": thread,
                "status": "pending_approval",
                "reply": "Thanks - a care specialist is reviewing your refund. No refund "
                "has been issued yet; we'll update you shortly.",
                "sla_due": p["sla_due"],
            }
        return {
            "thread_id": thread,
            "status": result["outcome"],
            "reply": result["reply"],
            "ticket": result.get("ticket"),
        }

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/v1/channels/{channel}/messages")
    def post_message(channel: str, body: MessageIn, c: Claims) -> dict:
        admit(channel, c)
        inp, cfg = start(channel, body, c)
        return view(g.invoke(inp, cfg), cfg)

    @app.post("/v1/channels/{channel}/messages/stream")
    def stream_message(channel: str, body: MessageIn, c: Claims):
        admit(channel, c)
        inp, cfg = start(channel, body, c)

        def events() -> Iterator[str]:
            for update in g.stream(inp, cfg, stream_mode="updates"):
                for node in update:
                    if node != "__interrupt__":
                        yield f"event: node\ndata: {json.dumps({'node': node})}\n\n"
            final = view(g.get_state(cfg).values | _interrupt(g, cfg), cfg)
            for word in final["reply"].split(" "):
                yield f"event: token\ndata: {json.dumps(word + ' ')}\n\n"
            yield f"event: done\ndata: {json.dumps(final)}\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.post("/v1/approvals/{thread_id}")
    def approve(thread_id: str, body: DecisionIn, c: Claims) -> dict:
        if "care-approver" not in c["roles"]:
            raise HTTPException(403, "care-approver role required")
        cfg = {"configurable": {"thread_id": thread_id}}
        if not g.get_state(cfg).next:
            raise HTTPException(409, "nothing pending on this thread")
        out = g.invoke(Command(resume={"decision": body.decision, "approver": c["sub"]}), cfg)
        return view(out, cfg)

    @app.post("/v1/ops/sla-sweep")
    def sla_sweep(body: SweepIn, c: Claims) -> dict:
        if "ops" not in c["roles"]:
            raise HTTPException(403, "ops role required")
        return {"expired": sweep_expired(g, s, body.now)}

    return app


def _interrupt(g: Any, cfg: dict) -> dict:
    st = g.get_state(cfg)
    pending = [i for t in st.tasks for i in t.interrupts]
    return {"__interrupt__": pending} if pending else {}


app = create_app  # uvicorn care_e2e.bff:app --factory
