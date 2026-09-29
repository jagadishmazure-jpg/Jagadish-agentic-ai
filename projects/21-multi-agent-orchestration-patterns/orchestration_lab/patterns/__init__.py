"""One module per orchestration pattern. Each exposes ``build(harness) -> compiled graph`` over
``PatternState`` and solves the same loan-exception task with the same worker agents."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from orchestration_lab.agents import WORKERS
from orchestration_lab.harness import Harness


def worker_node(h: Harness, agent: str, **kw: Any) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """A graph node that runs one worker turn and returns only the state update."""

    def node(state: dict[str, Any]) -> dict[str, Any]:
        return h.turn(agent, state, WORKERS[agent], **kw)[0]

    node.__name__ = agent
    return node


def finish_node(h: Harness) -> Callable[[dict[str, Any]], dict[str, Any]]:
    def finish(state: dict[str, Any]) -> dict[str, Any]:
        return h.finish(state, (state.get("control") or {}).get("stop"))

    return finish


def initial_state(case: dict[str, Any]) -> dict[str, Any]:
    return {
        "case": case,
        "ws": {},
        "turns": [],
        "exits": [],
        "transcript": [],
        "clock_ms": 0.0,
        "llm_calls": 0,
        "tokens": 0,
        "tool_calls": 0,
        "control": {},
    }


def failed_turn(update: dict[str, Any]) -> bool:
    return not update["turns"][-1]["ok"]
