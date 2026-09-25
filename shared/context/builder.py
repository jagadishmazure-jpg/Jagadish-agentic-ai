"""ContextBuilder: the one knowledge-plane runtime every agent uses.

query -> (expand) -> ACL + temporal pre-filter -> hybrid retrieve (BM25 + vector, RRF) ->
rerank -> sanitize (injections, secrets, PII) -> budgeted pack (policy/facts/history/tool I/O)
-> ContextBundle with a source map. Empty or failed retrieval raises a typed error so the
calling graph node can take its *degrade* exit instead of letting the model improvise.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date

from shared import faults
from shared.context.cache import SemanticCache
from shared.context.documents import Chunk, KnowledgeCorpus, Principal
from shared.context.packer import Budget, Evidence, PackedContext, pack
from shared.context.retrieval import Embedder, Hit, HybridRetriever
from shared.context.sanitize import sanitize
from shared.observability import telemetry


class RetrievalError(RuntimeError):
    """Base class: the knowledge plane could not supply evidence."""


class RetrievalUnavailableError(RetrievalError):
    """Search backend / index is down (or a chaos fault is injected)."""


class EmptyRetrievalError(RetrievalError):
    """Nothing visible to this principal, valid on this date, above the score floor."""


@dataclass
class ContextBundle:
    query: str
    hits: list[Hit]
    packed: PackedContext
    corpus: str
    corpus_version: str
    dropped_acl: int = 0
    dropped_temporal: int = 0
    injections: int = 0
    secrets: int = 0
    pii: int = 0
    cache_hit: bool = False
    expanded_query: str = ""

    @property
    def source_map(self) -> dict[str, dict[str, str]]:
        return self.packed.source_map

    @property
    def text(self) -> str:
        return self.packed.render()

    @property
    def chunk_ids(self) -> list[str]:
        return [h.chunk_id for h in self.hits]


@dataclass
class ContextBuilder:
    corpus: KnowledgeCorpus
    budget: Budget = field(default_factory=Budget)
    embedder: Embedder | None = None
    cache: SemanticCache | None = None
    min_score: float = 0.0
    min_coverage: float = 0.0
    redact_pii: bool = True
    rewriter: Callable[[str], str] | None = None
    _index: HybridRetriever | None = field(default=None, init=False, repr=False)
    _index_version: str | None = field(default=None, init=False, repr=False)

    # ------------------------------------------------------------------ retrieval
    def _retriever(self) -> HybridRetriever:
        v = self.corpus.version
        if self._index is None or self._index_version != v:  # re-index on version change
            self._index, self._index_version = HybridRetriever(self.corpus.chunks, self.embedder), v
        return self._index

    def expand(self, query: str) -> str:
        q = self.rewriter(query) if self.rewriter else query
        low = q.lower()
        extra = [s for term, syns in self.corpus.synonyms.items() if term in low for s in syns]
        return f"{q} {' '.join(extra)}".strip()

    def retrieve(
        self,
        query: str,
        principal: Principal,
        *,
        as_of: date | None = None,
        k: int = 5,
        kinds: Sequence[str] | None = None,
    ) -> tuple[list[Hit], int, int, str]:
        if faults.active(*faults.scopes("retrieval", self.corpus.name)):
            raise RetrievalUnavailableError(f"retrieval '{self.corpus.name}' unavailable")
        index = self._retriever()
        allowed, d_acl, d_time = set(), 0, 0
        for i, c in enumerate(index.chunks):
            if kinds and c.kind not in kinds:
                continue
            if not c.visible_to(principal):
                d_acl += 1  # security trim BEFORE ranking: hidden docs can't influence scores
            elif not c.valid_on(as_of):
                d_time += 1
            else:
                allowed.add(i)
        expanded = self.expand(query)
        hits = [
            h
            for h in index.search(expanded, k=k, allowed=allowed)
            if h.score >= self.min_score and h.coverage >= self.min_coverage
        ]
        return hits, d_acl, d_time, expanded

    # ------------------------------------------------------------------ build
    def build(
        self,
        query: str,
        principal: Principal,
        *,
        as_of: date | None = None,
        k: int = 5,
        kinds: Sequence[str] | None = None,
        facts: Sequence[tuple[str, str]] = (),
        history: Sequence[tuple[str, str]] = (),
        tool_io: Sequence[tuple[str, str]] = (),
        require_hits: bool = True,
    ) -> ContextBundle:
        t = telemetry()
        parent = t.current_parent()
        from opentelemetry import trace

        ctx = trace.set_span_in_context(parent) if parent else None
        with t.tracer.start_as_current_span(f"retrieve {self.corpus.name}", context=ctx) as sp:
            scope = f"{principal.scope_key()}|{as_of}|{k}|{kinds}"
            cached = None
            if self.cache is not None and not (facts or history or tool_io):
                cached = self.cache.get(query, scope, self.corpus.version)
            if cached is not None:
                sp.set_attribute("retrieval.cache_hit", True)
                return ContextBundle(**{**cached.__dict__, "cache_hit": True})
            try:
                hits, d_acl, d_time, expanded = self.retrieve(
                    query, principal, as_of=as_of, k=k, kinds=kinds
                )
            except RetrievalError as exc:
                sp.record_exception(exc)
                raise
            sp.set_attribute("retrieval.hits", len(hits))
            sp.set_attribute("retrieval.dropped_acl", d_acl)
            sp.set_attribute("retrieval.dropped_temporal", d_time)
            if require_hits and not hits:
                raise EmptyRetrievalError(
                    f"no evidence in '{self.corpus.name}' for principal {principal.id}"
                    + (f" as of {as_of}" if as_of else "")
                )
            evidence, inj, sec, pii = [], 0, 0, 0
            for h in hits:
                s = sanitize(h.chunk.text, redact_pii=self.redact_pii)
                inj, sec, pii = inj + s.injections, sec + s.secrets, pii + s.pii
                evidence.append(Evidence(h.chunk_id, s.text, "policy", _meta(h.chunk)))
            for section, items in (("facts", facts), ("history", history), ("tool_io", tool_io)):
                for sid, text in items:
                    s = sanitize(text, redact_pii=self.redact_pii)
                    inj, sec, pii = inj + s.injections, sec + s.secrets, pii + s.pii
                    evidence.append(Evidence(sid, s.text, section))
            packed = pack(evidence, self.budget)
            sp.set_attribute("retrieval.injections_neutralised", inj)
            sp.set_attribute("context.tokens", packed.total_tokens)
            bundle = ContextBundle(
                query,
                hits,
                packed,
                self.corpus.name,
                self.corpus.version,
                d_acl,
                d_time,
                inj,
                sec,
                pii,
                False,
                expanded,
            )
            if self.cache is not None and not (facts or history or tool_io):
                self.cache.put(query, scope, self.corpus.version, bundle)
            return bundle


def _meta(c: Chunk) -> dict[str, str]:
    return {
        "doc_id": c.doc_id,
        "title": c.title,
        "heading": " > ".join(c.heading_path),
        "version": c.version,
        "valid_from": str(c.valid_from or ""),
        "valid_to": str(c.valid_to or ""),
        "parent_id": c.parent_id or "",
    }
