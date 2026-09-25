"""RFP answer library as a knowledge product on the shared context builder."""

from __future__ import annotations

from datetime import date

from rfp_agent.knowledge import KB
from shared.context import Chunk, ContextBuilder, KnowledgeCorpus, Principal, sanitize

PRESALES = Principal.of("mi-rfp-agent", "presales")
TODAY = date(2026, 9, 25)
MIN_COVERAGE = 0.3

# Governance metadata the flat KB dict never had.
RESTRICTED = {
    "KB-PRC-001": {
        "title": "Pricing floor (deal desk only)",
        "text": "Discounts up to 35% on multi-year analytics platform deals are pre-approved "
        "by the deal desk.",
        "groups": {"deal-desk"},
    },
}
SUPERSEDED = {
    "KB-OPS-901": {
        "title": "Availability SLA (2025 edition)",
        "text": "Our SLA guarantees 99.5% monthly uptime with service credits.",
        "valid_from": date(2025, 1, 1),
        "valid_to": date(2025, 12, 31),
    },
}
CURRENT_FROM = {"KB-OPS-001": date(2026, 1, 1)}


def corpus() -> KnowledgeCorpus:
    chunks = [
        Chunk(
            kid,
            kid,
            v["text"],
            title=v["title"],
            parent_id="rfp-answer-library",
            groups=frozenset({"presales", "deal-desk"}),
            valid_from=CURRENT_FROM.get(kid),
            kind="kb",
        )
        for kid, v in KB.items()
    ]
    for kid, v in RESTRICTED.items():
        chunks.append(
            Chunk(
                kid,
                kid,
                v["text"],
                title=v["title"],
                parent_id="rfp-answer-library",
                groups=frozenset(v["groups"]),
                kind="kb",
            )
        )
    for kid, v in SUPERSEDED.items():
        chunks.append(
            Chunk(
                kid,
                kid,
                v["text"],
                title=v["title"],
                parent_id="rfp-answer-library",
                groups=frozenset({"presales", "deal-desk"}),
                valid_from=v["valid_from"],
                valid_to=v["valid_to"],
                version="2025",
                kind="kb",
            )
        )
    return KnowledgeCorpus("rfp-answer-library", chunks, refresh_sla="weekly + on approval")


def builder() -> ContextBuilder:
    return ContextBuilder(corpus())


def search(
    kb: ContextBuilder,
    question: str,
    principal: Principal = PRESALES,
    as_of: date | None = None,
    k: int = 3,
) -> list[dict[str, str]]:
    """Top approved entries as ``{"id", "title", "text"}`` (text sanitised). Raises
    ``RetrievalUnavailableError`` when the library is down (caller degrades)."""
    hits, *_ = kb.retrieve(question, principal, as_of=as_of or TODAY, k=k, kinds=["kb"])
    return [
        {
            "id": h.chunk_id,
            "title": h.chunk.title,
            "text": sanitize(h.chunk.text, redact_pii=False).text,
        }
        for h in hits
        if h.coverage >= MIN_COVERAGE
    ]
