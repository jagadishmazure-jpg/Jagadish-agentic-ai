"""SRE runbooks as a knowledge product on the shared context builder.

* ACL - database failover runbooks are visible only to the ``dba`` group; the investigator
  runs as an ``sre`` principal and never sees (or cites) them.
* temporal - RB-DB-07 has a superseded 2025 edition ("restart pods"); lookups are as-of the
  incident date, so an old incident gets the runbook that applied then.
* hybrid retrieval + sanitizer; outage raises ``RetrievalUnavailableError`` (typed).
"""

from __future__ import annotations

from datetime import date

from incident_agent.systems import RUNBOOKS
from shared.context import Chunk, ContextBuilder, KnowledgeCorpus, Principal, sanitize

SRE_AGENT = Principal.of("mi-incident-investigator", "sre")
TODAY = date(2026, 9, 25)
MIN_COVERAGE = 0.5

_EXTRA = [
    # (chunk id, symptom/title, text, groups, valid_from, valid_to, version)
    (
        "RB-DB-07@2025",
        "connection pool exhausted",
        "RB-DB-07 (2025 edition): restart the affected pods to release connections; do not "
        "roll back.",
        {"sre"},
        date(2025, 1, 1),
        date(2025, 12, 31),
        "2025",
    ),
    (
        "RB-DB-09",
        "primary database failover",
        "RB-DB-09: Promote the replica with dbctl failover --force; DBA approval required.",
        {"dba"},
        None,
        None,
        "1",
    ),
]


def corpus() -> KnowledgeCorpus:
    chunks = [
        Chunk(
            text.split(":", 1)[0],
            text.split(":", 1)[0],
            text,
            title=symptom,
            parent_id="sre-runbooks",
            groups=frozenset({"sre"}),
            valid_from=date(2026, 1, 1) if text.startswith("RB-DB-07") else None,
            kind="runbook",
        )
        for symptom, text in RUNBOOKS.items()
    ]
    for cid, title, text, groups, vf, vt, version in _EXTRA:
        chunks.append(
            Chunk(
                cid,
                cid.split("@")[0],
                text,
                title=title,
                parent_id="sre-runbooks",
                groups=frozenset(groups),
                valid_from=vf,
                valid_to=vt,
                version=version,
                kind="runbook",
            )
        )
    return KnowledgeCorpus("sre-runbooks", chunks, refresh_sla="on merge to runbooks repo")


def builder() -> ContextBuilder:
    return ContextBuilder(corpus())


def lookup(kb: ContextBuilder, symptom: str, as_of: date | None = None) -> tuple[str, str] | None:
    """Best runbook for a symptom as (chunk_id, sanitised text), or None if nothing matches.
    Raises ``RetrievalUnavailableError`` when search is down (caller degrades)."""
    hits, *_ = kb.retrieve(symptom, SRE_AGENT, as_of=as_of or TODAY, k=3, kinds=["runbook"])
    hits = [h for h in hits if h.coverage >= MIN_COVERAGE]
    if not hits:
        return None
    return hits[0].chunk_id, sanitize(hits[0].chunk.text, redact_pii=False).text
