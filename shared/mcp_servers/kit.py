"""Kit for MCP servers that wrap systems of record (official ``mcp`` SDK, FastMCP).

Conventions every server follows (doctrine: small tool surface, read-only first, writes with
idempotency keys, treat everything as auditable):

* ``@srv.read`` tools have no side effects.
* ``@srv.write`` tools MUST declare ``idempotency_key: str`` and ``dry_run: bool = True``.
  Dry-run is the default, so a confused caller previews instead of committing. A replayed
  idempotency key returns the original result instead of writing twice.
* Errors cross the wire as a JSON envelope ``{"error_type", "message", "retryable"}`` so the
  client-side gateway can re-raise typed errors.
* Chaos faults ``sor`` / ``sor:<server>`` / ``sor:<server>.<tool>`` make the server behave
  like an outage (retryable ``ConnectionError``).
"""

from __future__ import annotations

import functools
import inspect
import json
import threading
from collections.abc import Callable
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from shared import faults


class SorUnavailableError(ConnectionError):
    """The system of record behind this MCP server is down / timing out."""


def error_envelope(exc: BaseException) -> str:
    retryable = isinstance(exc, ConnectionError | TimeoutError) or bool(
        getattr(exc, "retryable", False)
    )
    return json.dumps(
        {"error_type": type(exc).__name__, "message": str(exc), "retryable": retryable}
    )


class SorServer:
    def __init__(self, name: str, instructions: str = "", system: str = ""):
        self.name = name
        self.system = system or name
        self.mcp = FastMCP(
            name, instructions=instructions or f"{name} system of record", log_level="WARNING"
        )
        self.kinds: dict[str, str] = {}
        self._idem: dict[tuple[str, str], Any] = {}
        self._lock = threading.Lock()

    def _wrap(
        self, fn: Callable[..., Any], tool: str, write: bool, dedupe: bool = True
    ) -> Callable[..., Any]:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                if faults.active(*faults.scopes("sor", self.name, tool)):
                    raise SorUnavailableError(f"{self.system} unavailable (503)")
                if write and dedupe and not kwargs.get("dry_run", True):
                    key = (tool, str(kwargs["idempotency_key"]))
                    with self._lock:
                        if key in self._idem:
                            prior = self._idem[key]
                            return (
                                {**prior, "idempotent_replay": True}
                                if isinstance(prior, dict)
                                else prior
                            )
                    out = fn(*args, **kwargs)
                    with self._lock:
                        self._idem[key] = out
                    return out
                return fn(*args, **kwargs)
            except ToolError:
                raise
            except Exception as exc:
                raise ToolError(error_envelope(exc)) from exc

        return wrapper

    def _register(
        self,
        fn: Callable[..., Any] | None,
        write: bool,
        name: str | None,
        description: str | None,
        dedupe: bool = True,
    ):
        def deco(f: Callable[..., Any]) -> Callable[..., Any]:
            tool = name or f.__name__
            if write:
                params = inspect.signature(f).parameters
                if "idempotency_key" not in params or "dry_run" not in params:
                    raise TypeError(f"write tool {tool} must take idempotency_key and dry_run")
                if params["dry_run"].default is not True:
                    raise TypeError(f"write tool {tool} must default dry_run=True")
            self.kinds[tool] = "write" if write else "read"
            desc = description or (inspect.getdoc(f) or tool)
            if write:
                desc = f"[WRITE: idempotent, dry_run by default] {desc}"
            self.mcp.add_tool(self._wrap(f, tool, write, dedupe), name=tool, description=desc)
            return f

        return deco(fn) if fn else deco

    def read(
        self,
        fn: Callable[..., Any] | None = None,
        *,
        name: str | None = None,
        description: str | None = None,
    ):
        return self._register(fn, False, name, description)

    def write(
        self,
        fn: Callable[..., Any] | None = None,
        *,
        name: str | None = None,
        description: str | None = None,
        dedupe: bool = True,
    ):
        """``dedupe=False`` when the backend owns idempotency (e.g. a payment provider that
        dedupes on the key itself) - the key is still required and passed through."""
        return self._register(fn, True, name, description, dedupe)

    def run_stdio(self) -> None:  # pragma: no cover - exercised via subprocess test
        self.mcp.run("stdio")
