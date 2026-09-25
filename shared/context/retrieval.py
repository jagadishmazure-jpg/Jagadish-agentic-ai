"""Hybrid retrieval: local BM25 + offline hashing-embedding vectors, fused with reciprocal
rank fusion, then a light lexical-coverage rerank. No network, no model downloads.

``Embedder`` is a protocol: swap ``HashingEmbedder`` for an Azure OpenAI embedding deployment
(pinned version) without touching callers.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from shared.context.documents import Chunk

_STOPWORDS = (
    "a an and are as at be by can do does for from has have how i if in is it its me my of on "
    "or our should so that the their them then there these this to us was we what when where "
    "which who why will with you your"
)
STOP = frozenset(_STOPWORDS.split())


def stem(w: str) -> str:
    for suf in ("ing", "ies", "ed", "es", "s"):
        if len(w) > len(suf) + 2 and w.endswith(suf):
            return w[: -len(suf)] + ("y" if suf == "ies" else "")
    return w


def tokenize(text: str) -> list[str]:
    return [
        stem(t) for t in re.findall(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", text.lower()) if t not in STOP
    ]


class Embedder(Protocol):
    dim: int

    def embed(self, text: str) -> list[float]: ...


class HashingEmbedder:
    """Deterministic offline embedder: hashed unigrams + char trigrams, L2-normalised."""

    def __init__(self, dim: int = 512, version: str = "hash-v1"):
        self.dim, self.version = dim, version

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        toks = tokenize(text)
        feats = toks + [t[i : i + 3] for t in toks for i in range(max(1, len(t) - 2))]
        for f in feats:
            h = int.from_bytes(hashlib.blake2b(f.encode(), digest_size=8).digest(), "big")
            vec[h % self.dim] += 1.0 if (h >> 63) & 1 else -1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))


class BM25:
    def __init__(self, chunks: Sequence[Chunk], k1: float = 1.5, b: float = 0.75):
        self.chunks, self.k1, self.b = list(chunks), k1, b
        self.docs = [Counter(tokenize(c.context_text)) for c in self.chunks]
        self.lens = [sum(d.values()) for d in self.docs]
        self.avg = (sum(self.lens) / len(self.lens)) if self.lens else 0.0
        df: Counter[str] = Counter()
        for d in self.docs:
            df.update(d.keys())
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: str, allowed: set[int] | None = None) -> list[tuple[int, float]]:
        q = tokenize(query)
        out = []
        for i, d in enumerate(self.docs):
            if allowed is not None and i not in allowed:
                continue
            s = 0.0
            for t in q:
                if t in d:
                    tf = d[t]
                    s += (
                        self.idf[t]
                        * tf
                        * (self.k1 + 1)
                        / (tf + self.k1 * (1 - self.b + self.b * self.lens[i] / (self.avg or 1)))
                    )
            if s > 0:
                out.append((i, s))
        return sorted(out, key=lambda x: -x[1])


class VectorIndex:
    def __init__(self, chunks: Sequence[Chunk], embedder: Embedder):
        self.embedder = embedder
        self.vecs = [embedder.embed(c.context_text) for c in chunks]

    def scores(
        self, query: str, allowed: set[int] | None = None, min_sim: float = 0.05
    ) -> list[tuple[int, float]]:
        qv = self.embedder.embed(query)
        out = [
            (i, cosine(qv, v)) for i, v in enumerate(self.vecs) if allowed is None or i in allowed
        ]
        return sorted([x for x in out if x[1] >= min_sim], key=lambda x: -x[1])


def rrf(rankings: Sequence[Sequence[int]], k: int = 60) -> dict[int, float]:
    """Reciprocal rank fusion: sum over lists of 1 / (k + rank)."""
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, idx in enumerate(ranking, 1):
            fused[idx] = fused.get(idx, 0.0) + 1.0 / (k + rank)
    return fused


@dataclass(frozen=True)
class Hit:
    chunk: Chunk
    score: float
    lexical_rank: int | None
    vector_rank: int | None
    coverage: float

    @property
    def chunk_id(self) -> str:
        return self.chunk.chunk_id


class HybridRetriever:
    def __init__(self, chunks: Sequence[Chunk], embedder: Embedder | None = None, rrf_k: int = 60):
        self.chunks = list(chunks)
        self.bm25 = BM25(self.chunks)
        self.vectors = VectorIndex(self.chunks, embedder or HashingEmbedder())
        self.rrf_k = rrf_k

    def search(
        self, query: str, k: int = 5, allowed: set[int] | None = None, rerank: bool = True
    ) -> list[Hit]:
        lex = [i for i, _ in self.bm25.scores(query, allowed)][: k * 4]
        vec = [i for i, _ in self.vectors.scores(query, allowed)][: k * 4]
        fused = rrf([lex, vec], self.rrf_k)
        q = set(tokenize(query))
        hits = []
        for i, s in fused.items():
            c = self.chunks[i]
            toks = set(tokenize(c.context_text))
            cov = len(q & toks) / len(q) if q else 0.0
            head = set(tokenize(" ".join(c.heading_path)))
            score = s + ((0.02 * cov + 0.01 * bool(q & head)) if rerank else 0.0)
            hits.append(
                Hit(
                    c,
                    score,
                    lex.index(i) + 1 if i in lex else None,
                    vec.index(i) + 1 if i in vec else None,
                    round(cov, 3),
                )
            )
        hits.sort(key=lambda h: -h.score)
        return hits[:k]
