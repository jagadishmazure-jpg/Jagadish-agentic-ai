"""Registry admin API + mounted A2A endpoints."""

from fastapi.testclient import TestClient

from control_plane.api import create_app

ADMIN = {"X-Admin-Token": "tok-platform-admin"}


def test_registry_api(net):
    c = TestClient(create_app(net))
    agents = {a["name"]: a for a in c.get("/registry/agents").json()}
    assert agents["sap-agent"]["side_effect"] == "reversible_write"
    assert c.post("/registry/agents/sap-agent/kill", json={"reason": "x"}).status_code == 403
    assert (
        c.post("/registry/agents/sap-agent/kill", json={"reason": "x"}, headers=ADMIN).status_code
        == 200
    )
    assert not net.cp.registry.get("sap-agent").enabled
    assert c.post("/registry/agents/sap-agent/revive", headers=ADMIN).status_code == 200
    assert c.post("/registry/agents/nope/promote", headers=ADMIN).status_code == 404


def test_register_then_gate(net):
    c = TestClient(create_app(net))
    rec = {
        "name": "faq-agent",
        "version": "1.0.0",
        "purpose": "answers product FAQs",
        "owner": "cx",
        "skills": {"answer": "read_only"},
        "tenants": ["northwind"],
        "eval_scores": {"task_success": 0.5, "policy_violation_rate": 0.0},
    }
    assert c.post("/registry/agents", json=rec, headers=ADMIN).status_code == 201
    r = c.post("/registry/agents/faq-agent/promote", headers=ADMIN)
    assert r.status_code == 409 and "task_success" in r.json()["detail"]


def test_mounted_a2a_endpoints(net):
    c = TestClient(create_app(net))
    card = c.get("/agents/demand-agent/.well-known/agent.json").json()
    assert card["skills"][0]["id"] == "forecast"
    body = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "message/send",
        "params": {
            "message": {
                "role": "user",
                "messageId": "m1",
                "parts": [{"kind": "data", "data": {"sku": "SKU-200", "weeks": 4}}],
                "metadata": {"skill": "forecast"},
            }
        },
    }
    r = c.post(
        "/agents/demand-agent/",
        json=body,
        headers={"x-tenant-id": "northwind", "x-caller-agent": "journey-agent"},
    ).json()
    assert r["result"]["status"]["state"] == "completed"
    assert c.get("/registry/audit").json()[-1]["decision"] == "allow"
