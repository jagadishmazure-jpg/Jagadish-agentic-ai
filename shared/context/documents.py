"""Knowledge documents, heading-aware chunking (parent-child IDs), ACL + temporal metadata."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
EVERYONE = "*"


@dataclass(frozen=True)
class Principal:
    """Who the context is being built for (user or agent acting on-behalf-of)."""

    id: str
    groups: frozenset[str] = frozenset()
    tenant: str | None = None

    @classmethod
    def of(cls, id: str, *groups: str, tenant: str | None = None) -> Principal:
        return cls(id, frozenset(groups), tenant)

    def scope_key(self) -> str:
        return f"{self.tenant}|{','.join(sorted(self.groups))}"


@dataclass(frozen=True)
class Document:
    doc_id: str
    title: str
    text: str
    groups: frozenset[str] = frozenset({EVERYONE})
    tenant: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    version: str = "1"
    kind: str = "policy"  # policy | kb | runbook | playbook | contract | note ...
    owner: str = ""


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    doc_id: str
    text: str
    title: str = ""
    heading_path: tuple[str, ...] = ()
    parent_id: str | None = None
    groups: frozenset[str] = frozenset({EVERYONE})
    tenant: str | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    version: str = "1"
    kind: str = "policy"
    meta: dict[str, str] = field(default_factory=dict, hash=False, compare=False)

    @property
    def context_text(self) -> str:
        """Chunk text prefixed with its heading path: a paragraph without its heading lies."""
        path = " > ".join((self.title, *self.heading_path)) if self.title else ""
        return f"{path}\n{self.text}" if path else self.text

    def visible_to(self, p: Principal) -> bool:
        if self.tenant is not None and self.tenant != p.tenant:
            return False
        return EVERYONE in self.groups or bool(self.groups & p.groups)

    def valid_on(self, as_of: date | None) -> bool:
        if as_of is None:
            return True
        if self.valid_from and as_of < self.valid_from:
            return False
        return not (self.valid_to and as_of > self.valid_to)


def chunk_document(doc: Document, max_words: int = 160) -> list[Chunk]:
    """Split on markdown headings. IDs: ``DOC::1``, ``DOC::1.2`` (child of ``DOC::1``);
    long sections are split on paragraphs into ``DOC::1.2~p2`` children."""
    sections: list[tuple[tuple[int, ...], tuple[str, ...], list[str]]] = []
    counters: list[int] = []
    headings: list[str] = []
    body: list[str] = []

    def flush() -> None:
        text = "\n".join(body).strip()
        if text:
            sections.append((tuple(counters), tuple(headings), [text]))
        body.clear()

    for line in doc.text.splitlines():
        m = _HEADING.match(line)
        if not m:
            body.append(line)
            continue
        flush()
        level = len(m.group(1))
        counters[:] = (counters + [0] * level)[:level]
        counters[level - 1] += 1
        headings[:] = (headings + [""] * level)[: level - 1]
        headings.append(m.group(2))
    flush()

    out: list[Chunk] = []
    common = dict(
        title=doc.title,
        groups=doc.groups,
        tenant=doc.tenant,
        valid_from=doc.valid_from,
        valid_to=doc.valid_to,
        version=doc.version,
        kind=doc.kind,
    )
    for nums, heads, (text,) in sections:
        sid = f"{doc.doc_id}::{'.'.join(map(str, nums))}" if nums else f"{doc.doc_id}::0"
        parent = f"{doc.doc_id}::{'.'.join(map(str, nums[:-1]))}" if len(nums) > 1 else doc.doc_id
        paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        if len(text.split()) <= max_words or len(paras) == 1:
            out.append(Chunk(sid, doc.doc_id, text, heading_path=heads, parent_id=parent, **common))
            continue
        for i, para in enumerate(paras, 1):
            out.append(
                Chunk(f"{sid}~p{i}", doc.doc_id, para, heading_path=heads, parent_id=sid, **common)
            )
    return out


@dataclass
class KnowledgeCorpus:
    """A knowledge product: named, owned, versioned. Version changes invalidate caches."""

    name: str
    chunks: list[Chunk]
    owner: str = "Jagadish Meduri"
    refresh_sla: str = "24h"
    synonyms: dict[str, Sequence[str]] = field(default_factory=dict)

    @classmethod
    def from_documents(cls, name: str, docs: Iterable[Document], **kw) -> KnowledgeCorpus:
        return cls(name, [c for d in docs for c in chunk_document(d)], **kw)

    @property
    def version(self) -> str:
        h = hashlib.sha256()
        for c in self.chunks:
            h.update(
                f"{c.chunk_id}|{c.version}|{c.text}|{sorted(c.groups)}|{c.tenant}|"
                f"{c.valid_from}|{c.valid_to}".encode()
            )
        return h.hexdigest()[:12]

    def get(self, chunk_id: str) -> Chunk | None:
        return next((c for c in self.chunks if c.chunk_id == chunk_id), None)

    def replace_chunk(self, chunk_id: str, **changes) -> None:
        self.chunks = [replace(c, **changes) if c.chunk_id == chunk_id else c for c in self.chunks]
