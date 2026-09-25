"""A2A task contract: agent card, schema rejection, guard, traceparent + tenant propagation."""

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel

from shared import faults
from shared.a2a import (
    A2AClient,
    A2AError,
    A2ARejection,
    A2AUnavailableError,
    AgentCard,
    AgentSkill,
    Skill,
    a2a_app,
)
from shared.observability import telemetry


class EchoIn(BaseModel):
    sku: str
    qty: int


def _app(guard=None):
    seen = {}

    def handle(inp, ctx):
        seen.update(tenant=ctx.tenant, traceparent=ctx.traceparent, caller=ctx.caller)
        return {"sku": inp.sku, "double": inp.qty * 2}

    card = AgentCard(
        name="echo-agent",
        description="doubles quantities",
        url="http://echo",
        skills=[AgentSkill(id="double", name="Double", description="x2")],
    )
    return a2a_app(card, {"double": Skill(EchoIn, handle)}, guard), seen


def test_card_and_round_trip_propagates_tenant_and_trace():
    app, seen = _app()
    c = A2AClient("echo-agent", TestClient(app), caller="journey")
    card = c.card()
    assert card.skills[0].inputSchema["required"] == ["sku", "qty"]
    with telemetry().tracer.start_as_current_span("root") as root:
        task = c.send("double", {"sku": "A", "qty": 2}, tenant="t1")
    assert task.status.state == "completed" and task.artifact("result")["double"] == 4
    assert seen["tenant"] == "t1" and seen["caller"] == "journey"
    trace_id = format(root.get_span_context().trace_id, "032x")
    assert trace_id in seen["traceparent"]


def test_schema_rejection_and_guard():
    def guard(ctx, card):
        if ctx.tenant == "blocked":
            raise A2ARejection("tenant not allowed")

    app, _ = _app(guard)
    c = A2AClient("echo-agent", TestClient(app), caller="journey")
    with pytest.raises(A2AError, match="schema rejected: qty"):
        c.send("double", {"sku": "A", "qty": "lots"}, tenant="t1")
    with pytest.raises(A2AError, match="tenant not allowed"):
        c.send("double", {"sku": "A", "qty": 1}, tenant="blocked")


def test_unavailable_peer_raises_typed_error():
    app, _ = _app()
    c = A2AClient("echo-agent", TestClient(app), caller="journey")
    faults.inject("a2a:echo-agent")
    with pytest.raises(A2AUnavailableError):
        c.send("double", {"sku": "A", "qty": 1}, tenant="t1")
