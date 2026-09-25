"""Local retrievers behind one interface (no network embeddings required).

- ``BM25Retriever``: Okapi BM25 implemented locally (default).
- ``EmbeddingRetriever``: cosine similarity over any ``embed(text) -> list[float]``
  function, e.g. Azure OpenAI embeddings in production or the offline ``hashing_embedder``.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from policy_qa.corpus import Chunk
from policy_qa.text import tokens


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float


class Retriever(Protocol):
    def search(self, query: str, k: int = 4) -> list[Hit]: ...


class BM25Retriever:
    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.k1, self.b = k1, b
        self.docs = [tokens(f"{c.doc} {c.section} {c.text}") for c in chunks]
        self.avgdl = sum(map(len, self.docs)) / len(self.docs)
        df = Counter(t for d in self.docs for t in set(d))
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, k: int = 4) -> list[Hit]:
        q = tokens(query)
        hits = []
        for chunk, doc in zip(self.chunks, self.docs, strict=True):
            tf = Counter(doc)
            score = sum(
                self.idf.get(t, 0.0)
                * tf[t]
                * (self.k1 + 1)
                / (tf[t] + self.k1 * (1 - self.b + self.b * len(doc) / self.avgdl))
                for t in q
                if t in tf
            )
            if score > 0:
                hits.append(Hit(chunk, round(score, 4)))
        return sorted(hits, key=lambda h: -h.score)[:k]


def hashing_embedder(dim: int = 256) -> Callable[[str], list[float]]:
    """Deterministic bag-of-words hashing embedder (offline stand-in for a real model)."""

    def embed(text: str) -> list[float]:
        v = [0.0] * dim
        for t in tokens(text):
            v[int(hashlib.md5(t.encode()).hexdigest(), 16) % dim] += 1.0
        norm = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / norm for x in v]

    return embed


class EmbeddingRetriever:
    def __init__(self, chunks: list[Chunk], embed: Callable[[str], list[float]]):
        self.chunks, self.embed = chunks, embed
        self.vectors = [embed(f"{c.section} {c.text}") for c in chunks]

    def search(self, query: str, k: int = 4) -> list[Hit]:
        q = self.embed(query)
        scored = [
            Hit(c, round(sum(a * b for a, b in zip(q, v, strict=True)), 4))
            for c, v in zip(self.chunks, self.vectors, strict=True)
        ]
        return sorted((h for h in scored if h.score > 0), key=lambda h: -h.score)[:k]
