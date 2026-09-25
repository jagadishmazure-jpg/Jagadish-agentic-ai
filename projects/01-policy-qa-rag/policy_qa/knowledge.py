"""HR/IT policy knowledge product on the shared context builder.

Same citable chunk IDs as ``corpus.load_chunks()`` plus governance metadata:

* ACL - ``HR-COMP`` (pay bands) is visible only to ``hr`` / ``people-managers``;
* temporal validity - the remote-work stipend has a superseded 2025 edition;
* hybrid retrieval (BM25 + vectors, RRF) + sanitizer + typed errors from ``shared.context``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from policy_qa.corpus import DOCS
from policy_qa.corpus import Chunk as QaChunk
from policy_qa.retriever import Hit
from shared.context import Chunk, ContextBuilder, KnowledgeCorpus, Principal

EMPLOYEE = Principal.of("employee", "employees")
HR_PARTNER = Principal.of("hr-partner", "employees", "hr")
CURRENT = date(2026, 1, 1)
TODAY = date(2026, 9, 25)

RESTRICTED = {
    "HR-COMP": (
        "Compensation Bands (confidential)",
        [
            (
                "Bands",
                "Salary bands for level L5 range from $150,000 to $185,000. Band data is "
                "confidential to HR and people managers.",
            ),
        ],
    ),
}
SUPERSEDED = [
    (
        "HR-REMOTEPREV-2",
        "HR-REMOTE-2025",
        "Remote Work Policy (2025)",
        "Stipend",
        "Remote employees receive a monthly remote work stipend of $30 to cover home internet "
        "and utilities. The stipend is paid through payroll.",
        date(2025, 1, 1),
        date(2025, 12, 31),
    ),
]


def corpus() -> KnowledgeCorpus:
    chunks: list[Chunk] = []
    for doc_id, (title, sections) in {**DOCS, **RESTRICTED}.items():
        groups = (
            frozenset({"hr", "people-managers"})
            if doc_id in RESTRICTED
            else frozenset({"employees"})
        )
        for i, (section, text) in enumerate(sections, start=1):
            valid_from = CURRENT if doc_id == "HR-REMOTE" and section == "Stipend" else None
            chunks.append(
                Chunk(
                    f"{doc_id}-{i}",
                    doc_id,
                    text,
                    title=title,
                    heading_path=(section,),
                    parent_id=doc_id,
                    groups=groups,
                    valid_from=valid_from,
                    kind="policy",
                )
            )
    for cid, doc_id, title, section, text, vf, vt in SUPERSEDED:
        chunks.append(
            Chunk(
                cid,
                doc_id,
                text,
                title=title,
                heading_path=(section,),
                parent_id=doc_id,
                groups=frozenset({"employees"}),
                valid_from=vf,
                valid_to=vt,
                version="2025",
            )
        )
    return KnowledgeCorpus(
        "hr-it-policies", chunks, owner="Jagadish Meduri", refresh_sla="24h + on publish"
    )


@dataclass
class ContextBuilderRetriever:
    """Adapts the shared ContextBuilder to the project's ``Retriever`` protocol. ACL trim and
    as-of filtering happen inside the builder, before ranking."""

    builder: ContextBuilder
    principal: Principal = EMPLOYEE
    as_of: date | None = TODAY

    def with_scope(
        self, principal: Principal | None, as_of: date | None
    ) -> ContextBuilderRetriever:
        return ContextBuilderRetriever(
            self.builder, principal or self.principal, as_of or self.as_of
        )

    def search(self, query: str, k: int = 4) -> list[Hit]:
        hits, *_ = self.builder.retrieve(query, self.principal, as_of=self.as_of, k=k)
        # Hybrid (RRF) scores are rank-based; keep hits that at least share a query term.
        return [
            Hit(
                QaChunk(
                    id=h.chunk_id,
                    doc=h.chunk.title,
                    section=h.chunk.heading_path[0] if h.chunk.heading_path else "",
                    text=h.chunk.text,
                ),
                round(h.score, 4),
            )
            for h in hits
            if h.coverage > 0
        ]


def default_retriever() -> ContextBuilderRetriever:
    return ContextBuilderRetriever(ContextBuilder(corpus()))
