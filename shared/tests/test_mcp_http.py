"""Streamable-HTTP transport: a FastMCP server in its own (uvicorn) process space is reached
by the same McpConnection + gateway used in-process (the docker-compose topology)."""

import socket
import threading
import time

import uvicorn

from shared.mcp_servers.demo_backends import DEMO_BACKENDS
from shared.mcp_servers.domains import BUILDERS
from shared.tools import ToolGateway, connect_urls


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_gateway_over_streamable_http():
    srv = BUILDERS["ticketing"](DEMO_BACKENDS["ticketing"]())
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(srv.mcp.streamable_http_app(), port=port, log_level="error")
    )
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    try:
        conns = connect_urls({"ticketing": f"http://127.0.0.1:{port}/mcp"})
        assert conns["ticketing"].transport == "http"
        gw = ToolGateway("t", "mi-test", conns, {"ticketing.*"})
        names = {t.name for t in conns["ticketing"].list_tools()}
        assert "list_tickets" in names
        assert isinstance(gw.call("ticketing", "list_tickets", account="Contoso"), list)
        conns["ticketing"].close()
    finally:
        server.should_exit = True
        t.join(timeout=5)
    assert gw.allowed("ticketing.list_tickets")
