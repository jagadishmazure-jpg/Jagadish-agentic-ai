"""Graph RAG for beneficial ownership over time.

Edges carry ``valid_from``/``valid_to``; ``beneficial_owners(entity, as_of)`` walks the graph
as of a date, multiplies percentages along each path and sums per natural person. The edges
used become citable evidence (``OWN::<edge id>``) for the memo."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from shared.context import sanitize


@dataclass(frozen=True)
class Edge:
    edge_id: str
    owner: str
    owned: str
    pct: float
    valid_from: date
    valid_to: date | None = None

    def valid_on(self, d: date) -> bool:
        return self.valid_from <= d and (self.valid_to is None or d <= self.valid_to)


NODES = {  # id -> (name, kind)
    "B-100": ("Northwind Fabrication LLC", "company"),
    "NWH": ("NW Holdings LP", "company"),
    "P-JANE": ("Jane Park", "person"),
    "P-MARCUS": ("Marcus Lee", "person"),
    "P-RAVI": ("Ravi Shah", "person"),
    "B-200": ("Globex Tooling Inc", "company"),
    "T-BLUE": ("Blue Harbor Trust", "trust"),
    "B-300": ("Initech Metals Corp", "company"),
    "P-VICTOR": ("Victor Sanz", "person"),
    "B-400": ("Contoso Castings LLC", "company"),
    "P-ANA": ("Ana Gomez", "person"),
}
D = date.fromisoformat
EDGES = [
    Edge("e1", "NWH", "B-100", 0.80, D("2019-01-01")),
    Edge("e2", "P-RAVI", "B-100", 0.20, D("2019-01-01")),
    Edge("e3", "P-JANE", "NWH", 0.60, D("2019-01-01"), D("2025-12-31")),
    Edge("e4", "P-MARCUS", "NWH", 0.40, D("2019-01-01"), D("2025-12-31")),
    Edge("e5", "P-JANE", "NWH", 0.30, D("2026-01-01")),
    Edge("e6", "P-MARCUS", "NWH", 0.70, D("2026-01-01")),
    Edge("e7", "T-BLUE", "B-200", 1.00, D("2020-05-01")),  # trust: beneficiaries not disclosed
    Edge("e8", "P-VICTOR", "B-300", 1.00, D("2018-03-01")),
    Edge("e9", "P-ANA", "B-400", 1.00, D("2021-07-01")),
]
THRESHOLD = 0.25


def beneficial_owners(entity: str, as_of: date) -> dict[str, Any]:
    owners: dict[str, float] = {}
    used: list[Edge] = []
    opaque: list[str] = []

    def walk(node: str, share: float, depth: int) -> None:
        if depth > 6:
            opaque.append(f"{node}: chain too deep")
            return
        ins = [e for e in EDGES if e.owned == node and e.valid_on(as_of)]
        if not ins:
            kind = NODES[node][1]
            if kind == "person":
                owners[node] = owners.get(node, 0) + share
            elif node != entity:
                opaque.append(f"{NODES[node][0]} ({kind}) has no disclosed owners")
            return
        for e in ins:
            used.append(e)
            walk(e.owner, share * e.pct, depth + 1)

    walk(entity, 1.0, 0)
    ubos = {NODES[p][0]: round(s, 4) for p, s in owners.items() if s >= THRESHOLD}
    return {
        "ubos": ubos,
        "all_owners": {NODES[p][0]: round(s, 4) for p, s in owners.items()},
        "opaque": opaque,
        "edges": used,
    }


def evidence(edges: list[Edge]) -> list[tuple[str, str]]:
    """Edges as citable, sanitised evidence chunks."""
    out = []
    for e in edges:
        until = f" until {e.valid_to}" if e.valid_to else ""
        text = (
            f"{NODES[e.owner][0]} owns {e.pct:.0%} of {NODES[e.owned][0]} "
            f"(from {e.valid_from}{until})"
        )
        out.append((f"OWN::{e.edge_id}", sanitize(text).text))
    return out
