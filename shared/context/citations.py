"""Citation checks against a source map (used by critics and eval metrics)."""

from __future__ import annotations

import re
from collections.abc import Iterable

_CITE = re.compile(r"\[([A-Za-z0-9][A-Za-z0-9_.:~#/-]*)\]")


def cited_ids(text: str) -> list[str]:
    return _CITE.findall(text)


def citation_coverage(text: str, valid_ids: Iterable[str]) -> tuple[float, list[str]]:
    """(fraction of substantive sentences carrying >=1 valid citation, invalid ids)."""
    valid = set(valid_ids)
    sentences = [s for s in re.split(r"(?<=[.!?])\s+|\n+", text) if len(s.split()) >= 4]
    invalid = sorted({c for c in cited_ids(text) if c not in valid})
    if not sentences:
        return 0.0, invalid
    ok = sum(1 for s in sentences if any(c in valid for c in cited_ids(s)))
    return ok / len(sentences), invalid
