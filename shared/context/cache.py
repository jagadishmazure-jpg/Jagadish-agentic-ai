"""Semantic cache for packed contexts, scoped by principal ACL + as-of date and invalidated
whenever the corpus version changes (re-index, supersession, ACL edit)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from shared.context.retrieval import Embedder, HashingEmbedder, cosine


@dataclass
class SemanticCache:
    threshold: float = 0.92
    embedder: Embedder = field(default_factory=HashingEmbedder)
    version: str | None = None
    entries: list[tuple[str, list[float], Any]] = field(default_factory=list)
    hits: int = 0
    misses: int = 0
    invalidations: int = 0

    def _check_version(self, version: str) -> None:
        if self.version != version:
            if self.version is not None:
                self.invalidations += 1
            self.entries.clear()
            self.version = version

    def get(self, query: str, scope: str, version: str) -> Any | None:
        self._check_version(version)
        qv = self.embedder.embed(query)
        for s, v, value in self.entries:
            if s == scope and cosine(qv, v) >= self.threshold:
                self.hits += 1
                return value
        self.misses += 1
        return None

    def put(self, query: str, scope: str, version: str, value: Any) -> None:
        self._check_version(version)
        self.entries.append((scope, self.embedder.embed(query), value))
