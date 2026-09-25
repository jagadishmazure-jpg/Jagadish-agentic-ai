import json
from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from care_e2e.bff import TokenBucket, create_app


def headers(tok="tok-ana", tenant="acme-retail"):
    return {"Authorization": f"Bearer {tok}", "X-Tenant-Id": tenant}


@pytest.fixture
def client(systems, graph):
    return TestClient(create_app(systems, graph))


MSG = {"message": "My shipment O-1001 is late, can I get a refund?"}


def test_message_round_trip_uses_identity_from_token(client, systems):
    r = client.post("/v1/channels/web/messages", json=MSG, headers=headers())
    assert r.status_code == 200 and r.json()["status"] == "refund_issued"
    # Ben's token asking about Ana's order: identity comes from claims, not the body
    r = client.post("/v1/channels/web/messages", json=MSG, headers=headers("tok-ben"))
    assert r.json()["status"] == "order_not_found"


def test_auth_channel_claim_and_tenant(client):
    assert (
        client.post("/v1/channels/web/messages", json=MSG, headers=headers("bad")).status_code
        == 401
    )
    assert (
        client.post(
            "/v1/channels/web/messages", json=MSG, headers=headers(tenant="globex")
        ).status_code
        == 403
    )
    r = client.post("/v1/channels/email/messages", json=MSG, headers=headers())
    assert r.status_code == 403 and "channel" in r.json()["detail"]


def test_rate_limit_per_tenant_and_channel(systems, graph):
    t = [0.0]
    app = create_app(systems, graph, TokenBucket(capacity=2, per_seconds=60, clock=lambda: t[0]))
    c = TestClient(app)
    ok = [
        c.post("/v1/channels/web/messages", json={"message": "hi"}, headers=headers())
        for _ in range(2)
    ]
    assert all(x.status_code == 200 for x in ok)
    r = c.post("/v1/channels/web/messages", json={"message": "hi"}, headers=headers())
    assert r.status_code == 429 and r.headers["Retry-After"]
    # another channel has its own bucket
    assert (
        c.post("/v1/channels/app/messages", json={"message": "hi"}, headers=headers()).status_code
        == 200
    )
    t[0] = 60.0  # refilled
    assert (
        c.post("/v1/channels/web/messages", json={"message": "hi"}, headers=headers()).status_code
        == 200
    )


def test_sse_stream_emits_nodes_tokens_and_done(client):
    with client.stream(
        "POST", "/v1/channels/web/messages/stream", json=MSG, headers=headers()
    ) as r:
        body = "".join(r.iter_text())
    events = [e for e in body.split("\n\n") if e]
    nodes = [json.loads(e.split("data: ")[1])["node"] for e in events if "event: node" in e]
    assert nodes[:3] == ["classify", "plan", "order"] and nodes[-1] == "finalize"
    done = json.loads(events[-1].split("data: ")[1])
    assert events[-1].startswith("event: done") and done["status"] == "refund_issued"
    assert any(e.startswith("event: token") for e in events)


def test_hitl_via_console_and_sla_sweep(client, systems):
    big = {"message": "My shipment O-1005 is late, can I get a refund?"}
    r = client.post("/v1/channels/web/messages", json=big, headers=headers()).json()
    assert r["status"] == "pending_approval" and "No refund has been issued" in r["reply"]
    thread = r["thread_id"]
    assert (
        client.post(
            f"/v1/approvals/{thread}", json={"decision": "approve"}, headers=headers()
        ).status_code
        == 403
    )  # customer can't approve
    ok = client.post(
        f"/v1/approvals/{thread}", json={"decision": "approve"}, headers=headers("tok-sam")
    )
    assert ok.json()["status"] == "refund_issued"
    r2 = client.post("/v1/channels/web/messages", json=big, headers=headers()).json()
    sweep = client.post(
        "/v1/ops/sla-sweep",
        json={"now": datetime(2026, 9, 26).isoformat()},
        headers=headers("tok-sam"),
    )
    assert sweep.json()["expired"] == [r2["thread_id"]]
    assert (
        client.post(
            f"/v1/approvals/{r2['thread_id']}",
            json={"decision": "approve"},
            headers=headers("tok-sam"),
        ).status_code
        == 409
    )
