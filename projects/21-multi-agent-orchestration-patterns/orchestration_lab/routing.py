"""What is still missing from the workspace, and who can supply it.

Used three ways: by the mock model (so a scripted supervisor / manager / swarm agent routes like a
sensible model would), by the deterministic fallback when a real model proposes an invalid
route, and by the guards that validate every proposed route against prerequisites.
"""

from __future__ import annotations

from typing import Any

WORKERS = ("researcher", "analyst", "policy", "drafter", "reviewer")
# agent -> what it contributes to the workspace
PRODUCES = {
    "researcher": "facts",
    "analyst": "analysis",
    "policy": "rules",
    "drafter": "draft",
    "reviewer": "review",
}
# agent -> workspace keys it needs before it can run (checked by every guard)
PREREQS: dict[str, tuple[str, ...]] = {
    "researcher": (),
    "analyst": ("facts",),
    "policy": (),
    "drafter": ("facts", "analysis", "rules"),
    "reviewer": ("draft",),
}
# capability cards: which tasks an agent can perform (used by magentic / blackboard replanning)
CAPABILITIES: dict[str, tuple[str, ...]] = {
    "researcher": ("facts", "analysis"),  # has the ratio calculator as a secondary tool
    "analyst": ("analysis",),
    "policy": ("rules",),
    "drafter": ("draft",),
    "reviewer": ("review",),
}
TASK_ORDER = ("facts", "analysis", "rules", "draft", "review")


def status(ws: dict[str, Any]) -> dict[str, Any]:
    """Compact, model-readable view of the workspace (no raw numbers)."""
    draft, review = ws.get("draft"), ws.get("review")
    return {
        "have": sorted(k for k in PRODUCES.values() if ws.get(k)),
        "draft_revision": draft["revision"] if draft else None,
        "review_revision": review["revision"] if review else None,
        "review_passed": bool(review and review["passed"]),
        "review_issues": list(review["issues"]) if review else [],
        "failed_agents": failed(ws),
    }


def failed(ws: dict[str, Any]) -> list[str]:
    """Agents (or teams) whose last attempt failed; a cleared error is stored as ''."""
    return sorted(k for k, v in (ws.get("errors") or {}).items() if v)


def ready(agent: str, ws: dict[str, Any]) -> bool:
    return all(ws.get(k) for k in PREREQS[agent])


def reviewed_current(ws: dict[str, Any]) -> bool:
    d, r = ws.get("draft"), ws.get("review")
    return bool(d and r and r["revision"] == d["revision"])


def next_step(st: dict[str, Any], *, order: tuple[str, ...] = WORKERS) -> str:
    """Next agent for a status dict, or FINISH. A failed review sends work back to drafter."""
    have = set(st["have"])
    if st["review_passed"]:
        return "FINISH"
    for agent in order:
        key = PRODUCES[agent]
        if agent == "reviewer":
            if "draft" in have and st["review_revision"] != st["draft_revision"]:
                return "reviewer"
            continue
        if agent == "drafter":
            if {"facts", "analysis", "rules"} <= have and (
                "draft" not in have or st["review_revision"] == st["draft_revision"]
            ):
                return "drafter"
            continue
        if key not in have:
            return agent
    return "FINISH"


def teams_todo(st: dict[str, Any], teams: dict[str, dict[str, list[str]]]) -> list[str]:
    """Teams whose deliverables are missing and whose inputs are ready (hierarchical top)."""
    have = set(st["have"])
    todo = []
    for name, spec in teams.items():
        needs, gives = set(spec["needs"]), set(spec["deliverables"])
        done = gives <= have and ("review" not in gives or st["review_passed"])
        if not done and needs <= have:
            todo.append(name)
    return todo
