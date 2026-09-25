"""Observability + deploy tooling behind the ops MCP server.

Logs, metrics and deploy history are read tools; ``rollback_deploy`` is the only write
(idempotency key, dry_run by default) and is called only after a human approves.
"""

from __future__ import annotations

from typing import Any

from incident_agent import systems as data
from incident_agent.systems import Systems
from shared.tools import ToolGateway, connect_backends

AGENT = "incident-investigator"
IDENTITY = "mi-incident-investigator"
ALLOW = {"ops.query_logs", "ops.get_metrics", "ops.recent_deploys", "ops.rollback_deploy"}


class OpsBackend:
    def __init__(self, systems: Systems):
        self.systems = systems

    def query_logs(self, service: str, pattern: str, minutes: int) -> dict[str, Any]:
        lines = [
            f"{t} {lvl} {msg}"
            for t, lvl, msg in data.LOGS.get(service, [])
            if pattern.upper() in lvl or pattern.lower() in msg.lower()
        ]
        return {"service": service, "lines": lines}

    def get_metrics(self, service: str, metric: str, minutes: int) -> dict[str, Any]:
        return dict(data.METRICS.get((service, metric)) or {})

    def recent_deploys(self, service: str, hours: int) -> dict[str, Any]:
        return {"service": service, "deploys": [dict(d) for d in data.DEPLOYS.get(service, [])]}

    def rollback_deploy(self, service: str, to_version: str, key: str) -> dict[str, Any]:
        return self.systems.deploys.rollback(service, to_version, idempotency_key=key)


def build_gateway(systems: Systems) -> ToolGateway:
    return ToolGateway(
        AGENT,
        IDENTITY,
        connect_backends({"ops": OpsBackend(systems)}),
        ALLOW,
        quotas={"ops.rollback_deploy": 3},
        timeout_s=5.0,
    )
