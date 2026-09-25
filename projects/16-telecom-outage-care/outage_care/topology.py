"""Service topology graph and redundancy-aware blast radius.

``depends_on`` lists upstream nodes; a node with several upstreams (dual-homed) stays up while
at least one upstream is up. ``blast_radius(dead)`` = everything that loses all upstream paths
when ``dead`` nodes fail (optionally on top of what is already down)."""

from __future__ import annotations

from collections.abc import Iterable

DEPENDS_ON: dict[str, list[str]] = {
    "CORE-1": [],
    "AGG-1": ["CORE-1"],
    "AGG-2": ["CORE-1"],
    "OLT-11": ["AGG-1"],
    "OLT-12": ["AGG-1"],
    "OLT-21": ["AGG-2"],
    "CELL-7": ["AGG-1", "AGG-2"],  # dual-homed
}
SERVICES = {  # account -> access node
    "A-100": "OLT-11",
    "A-200": "OLT-21",
    "A-300": "CELL-7",
    "A-400": "OLT-12",
}


def down_set(dead: Iterable[str]) -> set[str]:
    down = set(dead)
    changed = True
    while changed:
        changed = False
        for node, ups in DEPENDS_ON.items():
            if node not in down and ups and all(u in down for u in ups):
                down.add(node)
                changed = True
    return down


def blast_radius(dead: Iterable[str], already_down: Iterable[str] = ()) -> dict[str, list[str]]:
    base = down_set(already_down)
    after = down_set(set(dead) | base)
    newly = sorted(after - base - set(dead))
    return {
        "nodes": newly,
        "accounts": sorted(a for a, n in SERVICES.items() if n in after and n not in base),
    }


def path(account: str) -> list[str]:
    """Access node up to the core (first upstream at each hop) for context packs."""
    out, node = [], SERVICES[account]
    while node:
        out.append(node)
        ups = DEPENDS_ON[node]
        node = ups[0] if ups else ""
    return out


def affected(account: str, dead: Iterable[str]) -> bool:
    return SERVICES[account] in down_set(dead)
