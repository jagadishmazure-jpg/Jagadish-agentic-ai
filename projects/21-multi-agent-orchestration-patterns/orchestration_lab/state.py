"""State shared by every pattern graph, with reducers that make parallel branches safe.

* ``ws`` (workspace) merges dict updates, so concurrent workers each add their own key.
* ``turns`` / ``exits`` / ``transcript`` append.
* ``llm_calls`` / ``tokens`` / ``tool_calls`` add.
* ``clock_ms`` keeps the **max**: parallel branches start from the same clock and each writes
  its own finish time, so the state ends up holding the critical-path latency, not the sum.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


def merge_ws(old: dict[str, Any] | None, new: dict[str, Any] | None) -> dict[str, Any]:
    out = dict(old or {})
    for k, v in (new or {}).items():
        if k == "errors" and isinstance(v, dict):
            out["errors"] = {**out.get("errors", {}), **v}
        else:
            out[k] = v
    return out


def latest_max(old: float | None, new: float | None) -> float:
    return max(old or 0.0, new or 0.0)


class PatternState(TypedDict, total=False):
    case: dict[str, Any]  # {"loan_id", "ticket"}
    ws: Annotated[dict[str, Any], merge_ws]
    turns: Annotated[list[dict[str, Any]], operator.add]
    exits: Annotated[list[dict[str, str]], operator.add]
    transcript: Annotated[list[dict[str, Any]], operator.add]
    clock_ms: Annotated[float, latest_max]
    llm_calls: Annotated[int, operator.add]
    tokens: Annotated[int, operator.add]
    tool_calls: Annotated[int, operator.add]
    control: dict[str, Any]  # pattern bookkeeping; only written by non-parallel nodes
    result: dict[str, Any]


class ArenaState(TypedDict, total=False):
    pattern: str
    loan_id: str
    ticket: str
    run: dict[str, Any]  # the pattern's final PatternState, summarised
    result: dict[str, Any]
    human: dict[str, Any]
    exits: Annotated[list[dict[str, str]], operator.add]
    final: dict[str, Any]
