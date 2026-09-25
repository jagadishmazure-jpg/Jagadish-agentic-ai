"""One-liner wiring used by projects: backends -> MCP servers -> connections -> gateway."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool

from shared.mcp_servers.domains import BUILDERS
from shared.tools.connection import McpConnection


def connect_backends(backends: dict[str, Any]) -> dict[str, McpConnection]:
    """{'erp': MockERP(...)} -> {'erp': McpConnection} over the in-memory MCP transport."""
    return {
        name: McpConnection(name, server=BUILDERS[name](backend).mcp)
        for name, backend in backends.items()
    }


def connect_servers(servers: dict[str, Any]) -> dict[str, McpConnection]:
    """Project-owned ``SorServer``s (industry domains not in BUILDERS) -> connections."""
    return {name: McpConnection(name, server=srv.mcp) for name, srv in servers.items()}


async def load_stdio_tools_with_adapters(domain: str) -> list[BaseTool]:
    """Load a domain server's tools over stdio using ``langchain-mcp-adapters``
    (MultiServerMCPClient) - the portable path for async agents / other frameworks."""
    from langchain_mcp_adapters.client import MultiServerMCPClient

    client = MultiServerMCPClient(
        {
            domain: {
                "transport": "stdio",
                "command": sys.executable,
                "args": ["-m", "shared.mcp_servers", domain],
                "cwd": str(Path(__file__).resolve().parents[2]),
            }
        }
    )
    return await client.get_tools()
