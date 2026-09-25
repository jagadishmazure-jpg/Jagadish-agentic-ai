"""Run a domain MCP server over stdio with a demo backend: python -m shared.mcp_servers oms"""

import sys

from shared.mcp_servers.demo_backends import DEMO_BACKENDS
from shared.mcp_servers.domains import BUILDERS

if __name__ == "__main__":
    domain = sys.argv[1] if len(sys.argv) > 1 else "ticketing"
    BUILDERS[domain](DEMO_BACKENDS[domain]()).run_stdio()
