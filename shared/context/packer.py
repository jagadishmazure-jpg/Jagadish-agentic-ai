"""Token-budget packer with explicit allocations (policy / facts / history / tool I/O) and a
source map for citations. Budgets are set on purpose, per agent, not 'whatever fits'."""

from __future__ import annotations

from dataclasses import dataclass, field

from shared.observability import estimate_tokens

SECTIONS = ("policy", "facts", "history", "tool_io")


@dataclass(frozen=True)
class Budget:
    policy: int = 700
    facts: int = 300
    history: int = 150
    tool_io: int = 250

    @property
    def total(self) -> int:
        return self.policy + self.facts + self.history + self.tool_io


@dataclass(frozen=True)
class Evidence:
    source_id: str
    text: str
    section: str = "policy"
    meta: dict[str, str] = field(default_factory=dict, hash=False, compare=False)

    @property
    def tokens(self) -> int:
        return estimate_tokens(self.text)


@dataclass
class PackedContext:
    items: list[Evidence]
    used: dict[str, int]
    dropped: list[str]
    budget: Budget

    @property
    def source_map(self) -> dict[str, dict[str, str]]:
        return {e.source_id: {"section": e.section, **e.meta} for e in self.items}

    @property
    def source_ids(self) -> list[str]:
        return [e.source_id for e in self.items]

    def section(self, name: str) -> list[Evidence]:
        return [e for e in self.items if e.section == name]

    def render(self) -> str:
        blocks = []
        for sec in SECTIONS:
            items = self.section(sec)
            if items:
                blocks.append(
                    f"## {sec.upper()}\n" + "\n".join(f"[{e.source_id}] {e.text}" for e in items)
                )
        return "\n\n".join(blocks)

    @property
    def total_tokens(self) -> int:
        return sum(self.used.values())


def pack(evidence: list[Evidence], budget: Budget) -> PackedContext:
    """Greedy, order-preserving fill of each section's allocation; overflow is dropped
    (and reported) rather than silently truncated mid-sentence."""
    used = dict.fromkeys(SECTIONS, 0)
    kept, dropped, seen = [], [], set()
    for e in evidence:
        if e.source_id in seen or e.text.strip() in seen:
            continue  # dedupe
        cap = getattr(budget, e.section)
        if used[e.section] + e.tokens > cap:
            dropped.append(e.source_id)
            continue
        used[e.section] += e.tokens
        kept.append(e)
        seen.update({e.source_id, e.text.strip()})
    return PackedContext(kept, used, dropped, budget)
