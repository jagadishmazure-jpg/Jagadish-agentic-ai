"""Process-wide fault-injection registry used by chaos tests and ``--chaos`` demo flags.

Shared components consult it at their failure boundary, so a chaos test can "kill" a
dependency without monkeypatching project code:

* ``model`` / ``model:primary`` / ``model:fallback``  - chat model deployments
* ``retrieval`` / ``retrieval:<corpus>``              - the context builder
* ``sor`` / ``sor:<server>`` / ``sor:<server>.<tool>`` - MCP systems of record

``inject(name, times=n)`` fails only the next *n* checks (a transient fault). Leave ``times``
unset for a hard outage.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

_lock = threading.Lock()
_faults: dict[str, int | None] = {}


def inject(name: str, times: int | None = None) -> None:
    with _lock:
        _faults[name] = times


def clear(name: str | None = None) -> None:
    with _lock:
        if name is None:
            _faults.clear()
        else:
            _faults.pop(name, None)


def active(*names: str) -> str | None:
    """Return the first injected fault among ``names`` (consuming one transient shot)."""
    with _lock:
        for n in names:
            if n in _faults:
                left = _faults[n]
                if left is not None:
                    if left <= 1:
                        del _faults[n]
                    else:
                        _faults[n] = left - 1
                return n
    return None


def scopes(kind: str, name: str, sub: str | None = None) -> tuple[str, ...]:
    """Candidate fault names from broad to narrow, e.g. ('sor', 'sor:erp', 'sor:erp.get_po')."""
    out = [kind, f"{kind}:{name}"]
    if sub:
        out.append(f"{kind}:{name}.{sub}")
    return tuple(out)


@contextmanager
def fault(name: str, times: int | None = None) -> Iterator[None]:
    inject(name, times)
    try:
        yield
    finally:
        clear(name)
