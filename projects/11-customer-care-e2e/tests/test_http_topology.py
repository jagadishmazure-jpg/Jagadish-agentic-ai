"""docker-compose topology without Docker: the three MCP servers run as streamable-HTTP apps
(uvicorn threads) and the care graph reaches them via CARE_MCP_URLS."""

import gc
import socket
import threading
import time

import pytest
import uvicorn
from mcp.server.transport_security import TransportSecuritySettings

from care_e2e.graph import build_graph
from care_e2e.sor import backends
from care_e2e.systems import seed_systems
from shared.mcp_servers.domains import BUILDERS


def _port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def remote_servers(monkeypatch):
    remote = seed_systems()  # the servers' own copy of the systems of record
    servers, urls = [], []
    for d in ("oms", "crm", "payments"):
        srv = BUILDERS[d](backends(remote)[d])
        srv.mcp.settings.transport_security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True, allowed_hosts=["127.0.0.1:*"]
        )
        port = _port()
        server = uvicorn.Server(
            uvicorn.Config(srv.mcp.streamable_http_app(), port=port, log_level="error")
        )
        threading.Thread(target=server.run, daemon=True).start()
        servers.append(server)
        urls.append(f"{d}=http://127.0.0.1:{port}/mcp")
    for server in servers:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
    monkeypatch.setenv("CARE_MCP_URLS", ",".join(urls))
    yield remote
    for server in servers:
        server.should_exit = True


def test_refund_over_remote_mcp_servers(remote_servers):
    local = seed_systems()
    g = build_graph(local)
    req = {
        "request_id": "req-http",
        "channel": "web",
        "tenant": "acme-retail",
        "customer_id": "C100",
        "email": "ana@example.com",
        "message": "My shipment O-1001 is late, can I get a refund?",
    }
    r = g.invoke({"request": req}, {"configurable": {"thread_id": "http-1"}})
    assert r["outcome"] == "refund_issued"
    assert len(remote_servers.payments.refunds) == 1  # money moved in the remote system
    assert not local.payments.refunds
    del g  # close MCP sessions (finalizers) before the servers stop
    gc.collect()
