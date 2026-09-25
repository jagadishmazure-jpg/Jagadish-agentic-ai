"""Knowledge: carrier claim rules by tariff edition (temporal, per tenant contract) and the
proactive-communication policy. Tracking facts are never retrieved from here; they come only
from TMS scan events."""

from __future__ import annotations

from datetime import date

from shared.context import (
    Budget,
    ContextBuilder,
    Document,
    KnowledgeCorpus,
    Principal,
    SemanticCache,
    chunk_document,
)

D = date.fromisoformat
OPS = frozenset({"logistics-ops"})


def _doc(
    doc_id: str,
    title: str,
    body: str,
    kind: str,
    start: str,
    end: str | None = None,
    tenant: str | None = None,
) -> Document:
    return Document(
        doc_id,
        title,
        f"# {title}\n{doc_id}: {body}",
        groups=OPS,
        tenant=tenant,
        kind=kind,
        valid_from=D(start),
        valid_to=D(end) if end else None,
        version=start,
        owner="carrier-management",
    )


DOCS = [
    _doc(
        "CLM-RIDGELINE-2025",
        "Ridgeline Freight claim rules 2025 edition",
        "Freight damage claim against carrier Ridgeline Freight: file within 180 days of "
        "delivery with the bill of lading (BOL), delivery receipt and a damage description. "
        "Claimed amount must be itemised.",
        "claim_rules",
        "2025-01-01",
        "2026-06-30",
    ),
    _doc(
        "CLM-RIDGELINE-2026",
        "Ridgeline Freight claim rules 2026 edition",
        "Freight damage claim against carrier Ridgeline Freight: file within 120 days of "
        "delivery. Required: bill of lading (BOL), proof of delivery (POD) with the exception "
        "noted at delivery, photos and a damage description. Claimed amount must be itemised.",
        "claim_rules",
        "2026-07-01",
    ),
    _doc(
        "CLM-COASTAL-2026",
        "Coastal Carriers claim rules 2026 edition",
        "Freight damage claim against carrier Coastal Carriers: file within 60 days of "
        "delivery with BOL and POD exception.",
        "claim_rules",
        "2026-01-01",
    ),
    _doc(
        "COMMS-PROACTIVE-2026",
        "Proactive delay communication policy",
        "Send a proactive delay notice only when the slipped milestone is confirmed by a "
        "high-confidence event (carrier EDI or driver app scan) and scans are current. Never "
        "speculate on the cause, never estimate a location, and give the new ETA only when "
        "the TMS provides one.",
        "policy",
        "2026-01-01",
    ),
]


def corpus() -> KnowledgeCorpus:
    return KnowledgeCorpus(
        "logistics-knowledge",
        [c for d in DOCS for c in chunk_document(d)],
        synonyms={"damage": ["damaged", "crushed", "claim"]},
        refresh_sla="on carrier tariff publication",
    )


def principal(tenant: str | None = None) -> Principal:
    return Principal.of("mi-exception-agent", "logistics-ops", tenant=tenant)


def builder() -> ContextBuilder:
    return ContextBuilder(
        corpus(),
        budget=Budget(policy=700, facts=300, history=0, tool_io=300),
        cache=SemanticCache(),
    )
