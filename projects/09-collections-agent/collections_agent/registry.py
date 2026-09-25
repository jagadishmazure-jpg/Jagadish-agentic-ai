"""Scoped tool registry: separate read vs write identities (least privilege).

Each tool declares the scope it needs. Each graph node receives a ``ScopedClient`` bound to
ONE identity; calling a tool outside that identity's scopes raises ``PermissionDenied`` and is
audited. Identities map 1:1 to what would be separate managed identities / service principals
with their own credentials in production.

Transport: when ``use_mcp`` is called (``seed_systems`` does), every permitted call is routed
through that identity's MCP ToolGateway instead of calling the Python function directly.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from collections_agent.audit import AuditLog

IDENTITIES: dict[str, set[str]] = {
    "collections-reader": {"accounts:read", "history:read"},
    "plan-proposer": {"accounts:read", "plans:propose"},
    "plan-writer": {"plans:write"},  # used only after human approval
    "outreach-sender": {"messages:send"},
}


class PermissionDenied(Exception):
    pass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    scope: str
    fn: Callable[..., Any]
    writes: bool = False


class ToolRegistry:
    def __init__(self, audit: AuditLog, clock: Callable[[], str]):
        self._tools: dict[str, ToolSpec] = {}
        self.audit, self.clock = audit, clock
        self.routes: dict[str, tuple[str, str, bool]] = {}
        self.gateways: dict[str, Any] = {}
        self.write_args: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None

    def use_mcp(
        self,
        routes: dict[str, tuple[str, str, bool]],
        gateways: dict[str, Any],
        write_args: Callable[[str, dict[str, Any]], dict[str, Any]],
    ) -> None:
        self.routes, self.gateways, self.write_args = routes, gateways, write_args

    def scopes(self) -> dict[str, str]:
        return {n: t.scope for n, t in self._tools.items()}

    def register(self, name: str, scope: str, fn: Callable[..., Any], writes: bool = False):
        self._tools[name] = ToolSpec(name, scope, fn, writes)

    def tools_for(self, identity: str) -> list[str]:
        return sorted(n for n, t in self._tools.items() if t.scope in IDENTITIES[identity])

    def client(self, identity: str) -> ScopedClient:
        if identity not in IDENTITIES:
            raise PermissionDenied(f"unknown identity {identity}")
        return ScopedClient(self, identity)

    def invoke(self, identity: str, name: str, **kwargs: Any) -> Any:
        tool = self._tools[name]
        if tool.scope not in IDENTITIES[identity]:
            self.audit.record(
                identity, "permission_denied", self.clock(), tool=name, required_scope=tool.scope
            )
            raise PermissionDenied(f"{identity} lacks scope {tool.scope} for {name}")
        if name in self.routes and identity in self.gateways:
            server, mcp_tool, write = self.routes[name]
            args = self.write_args(name, kwargs) if write and self.write_args else kwargs
            result = self.gateways[identity].call(server, mcp_tool, **args)
        else:
            result = tool.fn(**kwargs)
        self.audit.record(
            identity, f"tool:{name}", self.clock(), scope=tool.scope, write=tool.writes, args=kwargs
        )
        return result


@dataclass(frozen=True)
class ScopedClient:
    registry: ToolRegistry
    identity: str

    def call(self, name: str, **kwargs: Any) -> Any:
        return self.registry.invoke(self.identity, name, **kwargs)
