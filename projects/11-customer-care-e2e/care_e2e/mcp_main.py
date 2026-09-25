"""Run one care system of record as a standalone MCP server over streamable HTTP.

python -m care_e2e.mcp_main oms --port 8000     # docker-compose service mcp-oms
"""

from __future__ import annotations

import argparse
import os

import uvicorn
from mcp.server.transport_security import TransportSecuritySettings

from care_e2e.sor import backends
from care_e2e.systems import seed_systems
from shared.mcp_servers.domains import BUILDERS


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("domain", choices=["oms", "crm", "payments"])
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8000)
    a = ap.parse_args(argv)
    srv = BUILDERS[a.domain](backends(seed_systems())[a.domain])
    # keep DNS-rebinding protection on, but allow the compose / Container Apps service name
    hosts = os.getenv("MCP_ALLOWED_HOSTS", f"mcp-{a.domain}:*,localhost:*,127.0.0.1:*")
    srv.mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True, allowed_hosts=hosts.split(",")
    )
    uvicorn.run(srv.mcp.streamable_http_app(), host=a.host, port=a.port, log_level="info")


if __name__ == "__main__":
    main()
