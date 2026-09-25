"""Long-term memory on a LangGraph ``BaseStore``.

Namespaces are ``("memory", user_id, kind)`` and every method takes the *authenticated*
``user_id`` (from the run config, never from message text), so a query can only ever reach
that customer's namespace. The Store's vector index (``InMemoryStore(index=...)`` here,
``PostgresStore`` with pgvector in production) provides semantic similarity; this module
adds recency decay, confidence, TTL and forgetting on top.

Score = 0.6 * similarity + 0.25 * recency + 0.15 * confidence, where
recency = 0.5 ** (age_days / half_life[kind]). Expired items are never returned and are
deleted by ``sweep()``. TTL is enforced here against an injectable clock (deterministic
tests); PostgresStore's native ``TTLConfig`` would do the sweeping in production.

``forget()`` deletes values and leaves a content-free tombstone in ``("audit", user_id)``
recording what kind of thing was erased and when, so erasure is provable without keeping
the erased data.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from langgraph.store.base import BaseStore
from langgraph.store.memory import InMemoryStore

from memory_agent.schema import (
    DAY,
    HALF_LIFE_DAYS,
    KEYS,
    KINDS,
    TTL_SECONDS,
    HistoryItem,
    MemoryRecord,
)
from shared import faults
from shared.context import HashingEmbedder

W_SIM, W_REC, W_CONF = 0.6, 0.25, 0.15
MIN_SCORE = 0.3
Clock = Callable[[], float]


class MemoryUnavailableError(ConnectionError):
    """The memory store is down (chaos fault ``retrieval`` / ``retrieval:memory``)."""


def make_store(dim: int = 1024) -> InMemoryStore:
    emb = HashingEmbedder(dim=dim)
    return InMemoryStore(
        index={
            "dims": dim,
            "embed": lambda texts: [emb.embed(t) for t in texts],
            "fields": ["text"],
        }
    )


def _check() -> None:
    if faults.active("retrieval", "retrieval:memory"):
        raise MemoryUnavailableError("memory store unavailable (injected)")


def ns(user_id: str, kind: str) -> tuple[str, ...]:
    if not user_id or "/" in user_id:
        raise ValueError("a valid authenticated user_id is required")
    return ("memory", user_id, kind)


@dataclass
class Recalled:
    record: MemoryRecord
    score: float
    similarity: float


class MemoryStore:
    def __init__(self, store: BaseStore, clock: Clock = time.time):
        self.store, self.clock = store, clock

    # ------------------------------------------------------------------ read
    def get(self, user_id: str, kind: str, key: str) -> MemoryRecord | None:
        _check()
        item = self.store.get(ns(user_id, kind), key)
        if item is None:
            return None
        rec = MemoryRecord(**item.value)
        return None if self._expired(rec) else rec

    def all(self, user_id: str) -> list[MemoryRecord]:
        _check()
        out = []
        for kind in KINDS:
            for item in self.store.search(ns(user_id, kind), limit=1000):
                rec = MemoryRecord(**item.value)
                if not self._expired(rec):
                    out.append(rec)
        return out

    def search(self, user_id: str, query: str, k: int = 5) -> list[Recalled]:
        """Semantic + episodic memories ranked by relevance x recency x confidence.
        Preferences (procedural) are not ranked: ``preferences()`` loads them every turn."""
        _check()
        now = self.clock()
        hits = []
        for kind in ("profile", "episode"):
            for item in self.store.search(ns(user_id, kind), query=query, limit=20):
                rec = MemoryRecord(**item.value)
                if self._expired(rec):
                    continue
                sim = max(0.0, float(item.score or 0.0))
                age_days = max(0.0, (now - rec.updated_at) / DAY)
                recency = 0.5 ** (age_days / HALF_LIFE_DAYS[kind])
                score = W_SIM * sim + W_REC * recency + W_CONF * rec.confidence
                if sim > 0.05 and score >= MIN_SCORE:
                    hits.append(Recalled(rec, round(score, 4), round(sim, 4)))
        return sorted(hits, key=lambda h: -h.score)[:k]

    def preferences(self, user_id: str) -> list[MemoryRecord]:
        _check()
        recs = [MemoryRecord(**i.value) for i in self.store.search(ns(user_id, "preference"))]
        return [r for r in recs if not self._expired(r)]

    def _expired(self, rec: MemoryRecord) -> bool:
        return rec.expires_at is not None and rec.expires_at <= self.clock()

    # ------------------------------------------------------------------ write
    def upsert(
        self, user_id: str, kind: str, key: str, value: str, confidence: float, source: str
    ) -> MemoryRecord:
        _check()
        now = self.clock()
        old = self.get(user_id, kind, key)
        history = list(old.history) if old else []
        if old and old.value != value:
            history.append(HistoryItem(value=old.value, source=old.source, replaced_at=now))
        ttl = TTL_SECONDS[kind]
        desc = KEYS.get(key, (kind, "past conversation we talked about, discussed last time"))[1]
        rec = MemoryRecord(
            kind=kind,  # type: ignore[arg-type]
            key=key,
            value=value,
            confidence=confidence,
            source=source,  # type: ignore[arg-type]
            created_at=old.created_at if old else now,
            updated_at=now,
            expires_at=now + ttl if ttl else None,
            history=history[-5:],  # bounded: old values are not kept forever
            text=f"{desc}: {value}",
        )
        self.store.put(ns(user_id, kind), key, rec.model_dump())
        return rec

    # ------------------------------------------------------------------ forget
    def forget(self, user_id: str, key: str | None = None) -> int:
        """Delete one key (every kind) or, with ``key=None``, everything for the user."""
        _check()
        n = 0
        for kind in KINDS:
            for item in self.store.search(ns(user_id, kind), limit=1000):
                if key is None or item.key == key:
                    self.store.delete(ns(user_id, kind), item.key)
                    n += 1
        self._tombstone(user_id, "all" if key is None else key, n)
        return n

    def _tombstone(self, user_id: str, scope: str, n: int) -> None:
        now = self.clock()
        self.store.put(
            ("audit", user_id),
            f"forget-{int(now * 1000)}-{uuid.uuid4().hex[:8]}",
            {"scope": scope, "n": n, "at": now},
        )

    def sweep(self) -> int:
        """Delete expired items across all users (the job a TTL sweeper runs)."""
        n = 0
        for namespace in self.store.list_namespaces(prefix=("memory",)):
            for item in self.store.search(namespace, limit=10_000):
                if self._expired(MemoryRecord(**item.value)):
                    self.store.delete(namespace, item.key)
                    n += 1
        return n

    def audit(self, user_id: str) -> list[dict[str, Any]]:
        return [i.value for i in self.store.search(("audit", user_id), limit=1000)]

    # ------------------------------------------------------------------ consent
    def consent(self, user_id: str, default: bool = False) -> bool:
        _check()
        item = self.store.get(("consent", user_id), "memory")
        return bool(item.value["granted"]) if item else default

    def set_consent(self, user_id: str, granted: bool) -> None:
        _check()
        self.store.put(("consent", user_id), "memory", {"granted": granted, "at": self.clock()})
