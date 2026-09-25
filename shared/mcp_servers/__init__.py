"""MCP servers (official SDK / FastMCP) wrapping systems of record."""

from shared.mcp_servers.domains import (
    BUILDERS,
    build_analytics_server,
    build_crm_server,
    build_erp_server,
    build_oms_server,
    build_ops_server,
    build_payments_server,
    build_ticketing_server,
)
from shared.mcp_servers.kit import SorServer, SorUnavailableError

__all__ = [
    "BUILDERS",
    "SorServer",
    "SorUnavailableError",
    "build_analytics_server",
    "build_crm_server",
    "build_erp_server",
    "build_oms_server",
    "build_ops_server",
    "build_payments_server",
    "build_ticketing_server",
]
