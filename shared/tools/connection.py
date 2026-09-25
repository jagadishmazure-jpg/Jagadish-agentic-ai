"""Sync MCP client connection for LangGraph nodes.

Holds a real MCP ``ClientSession`` (JSON-RPC over the SDK's in-memory transport for an
in-process FastMCP server, or over stdio for a subprocess server) on one background event
loop, and exposes blocking ``call()`` / ``list_tools()`` with timeouts so synchronous graph
nodes can use MCP without async plumbing.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import threading
import weakref
from collections.abc import Sequence
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import timedelta
from typing import Any

from mcp import ClientSession, StdioServerParameters, types
from mcp.client.stdio import stdio_client
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session

_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = threading.Lock()


def background_loop() -> asyncio.AbstractEventLoop:
    global _loop
    with _loop_lock:
        if _loop is None:
            _loop = asyncio.new_event_loop()
            threading.Thread(target=_loop.run_forever, name="mcp-client-loop", daemon=True).start()
    return _loop


class _Holder:
    """Session state kept outside the connection so a finalizer can close it."""

    def __init__(self) -> None:
        self.session: ClientSession | None = None
        self.ready = threading.Event()
        self.error: BaseException | None = None
        self.closed: asyncio.Event | None = None
        self.task: Any = None

    def close(self, wait: bool = False) -> None:
        loop = background_loop()
        if self.closed is not None and not loop.is_closed():
            loop.call_soon_threadsafe(self.closed.set)
            # Never block when called from a GC finalizer (possibly on the loop thread).
            if wait and threading.current_thread().name != "mcp-client-loop":
                with contextlib.suppress(Exception):
                    self.task.result(timeout=5)
            self.closed = None


class McpConnection:
    def __init__(
        self,
        name: str,
        *,
        server: FastMCP | None = None,
        stdio: StdioServerParameters | None = None,
        connect_timeout_s: float = 20.0,
    ):
        if (server is None) == (stdio is None):
            raise ValueError("pass exactly one of server= or stdio=")
        self.name = name
        self.transport = "memory" if server is not None else "stdio"
        self._h = _Holder()
        loop = background_loop()
        self._h.task = asyncio.run_coroutine_threadsafe(self._hold(self._h, server, stdio), loop)
        if not self._h.ready.wait(connect_timeout_s):
            raise TimeoutError(f"MCP server {name} did not start")
        if self._h.error:
            raise self._h.error
        self._finalizer = weakref.finalize(self, self._h.close)
        self._tools: list[types.Tool] | None = None

    @staticmethod
    async def _hold(
        h: _Holder, server: FastMCP | None, stdio: StdioServerParameters | None
    ) -> None:
        h.closed = asyncio.Event()
        try:
            if server is not None:
                async with create_connected_server_and_client_session(
                    server, read_timeout_seconds=timedelta(seconds=30)
                ) as session:
                    h.session = session
                    h.ready.set()
                    await h.closed.wait()
            else:
                async with (
                    stdio_client(stdio) as (read, write),
                    ClientSession(read, write) as session,
                ):
                    await session.initialize()
                    h.session = session
                    h.ready.set()
                    await h.closed.wait()
        except BaseException as exc:  # surface startup failures to the caller
            h.error = exc
            h.ready.set()

    def _run(self, coro: Any, timeout_s: float) -> Any:
        fut = asyncio.run_coroutine_threadsafe(coro, background_loop())
        try:
            return fut.result(timeout=timeout_s)
        except FutureTimeout as exc:
            fut.cancel()
            raise TimeoutError(f"MCP {self.name} call timed out after {timeout_s}s") from exc

    def list_tools(self, timeout_s: float = 10.0) -> list[types.Tool]:
        if self._tools is None:
            assert self._h.session is not None
            self._tools = self._run(self._h.session.list_tools(), timeout_s).tools
        return self._tools

    def call(
        self, tool: str, args: dict[str, Any], timeout_s: float = 10.0
    ) -> types.CallToolResult:
        assert self._h.session is not None, "connection closed"
        return self._run(self._h.session.call_tool(tool, args), timeout_s)

    def close(self) -> None:
        self._finalizer.detach()
        self._h.close(wait=True)


def payload(result: types.CallToolResult) -> Any:
    """Structured payload of a successful call (unwraps FastMCP's {'result': ...})."""
    data = result.structuredContent
    if data is None:
        texts: Sequence[str] = [c.text for c in result.content if isinstance(c, types.TextContent)]
        raw = "".join(texts)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return raw
    if isinstance(data, dict) and set(data) == {"result"}:
        return data["result"]
    return data


def error_info(result: types.CallToolResult) -> dict[str, Any]:
    text = "".join(c.text for c in result.content if isinstance(c, types.TextContent))
    start = text.find("{")
    if start >= 0:
        try:
            return json.loads(text[start:])
        except json.JSONDecodeError:
            pass
    return {"error_type": "ToolError", "message": text, "retryable": False}
