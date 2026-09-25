"""Knowledge plane: care policy corpus on the shared context builder.

* temporal: late-delivery policy has a 2025 and a 2026 edition; lookups are as-of the
  **purchase date** (the business event), not today.
* ACL: the internal fraud playbook is visible to ``fraud-ops`` only; the care agent runs as a
  ``care`` principal and never retrieves it.
* CRM cases become per-request evidence chunks carrying their own ACL groups + tenant, so the
  same trimming applies to case history (a billing-only or fraud note never reaches the model).
"""

from __future__ import annotations

from datetime import date
from typing import Any

from shared.context import (
    Budget,
    Chunk,
    ContextBuilder,
    Document,
    KnowledgeCorpus,
    Principal,
    SemanticCache,
    chunk_document,
)

CARE_AGENT_GROUPS = ("care",)


def principal(tenant: str | None) -> Principal:
    return Principal.of("mi-care-agent", *CARE_AGENT_GROUPS, tenant=tenant)


DOCS = [
    Document(
        "CARE-LATE-2026",
        "Late delivery policy (2026 edition)",
        "# Late delivery refunds\nCARE-LATE-2026: For orders placed from 1 January 2026, a "
        "shipment delivered or still in transit 5 or more days after the promised date "
        "qualifies for a refund of the shipping fee. At 10 or more days late, or when the "
        "carrier declares the parcel lost, the whole order is refunded to the original "
        "payment method.",
        valid_from=date(2026, 1, 1),
        version="2026",
        owner="care-policy",
    ),
    Document(
        "CARE-LATE-2025",
        "Late delivery policy (2025 edition)",
        "# Late delivery refunds\nCARE-LATE-2025: For orders placed in 2025, a shipment 7 or "
        "more days late qualifies for a shipping fee refund. Only a parcel the carrier declares "
        "lost is refunded in full.",
        valid_from=date(2025, 1, 1),
        valid_to=date(2025, 12, 31),
        version="2025",
        owner="care-policy",
    ),
    Document(
        "CARE-AUTO-1",
        "Refund approvals",
        "# Refund approvals\nCARE-AUTO-1: Late-delivery refunds up to $50 are issued "
        "automatically. Larger refunds require approval by a care specialist. Refunds always "
        "go back to the original payment method.",
        owner="care-policy",
    ),
    Document(
        "CARE-COMMS-1",
        "Customer communication rules",
        "# Customer communication\nCARE-COMMS-1: Never tell a customer a refund has been "
        "issued before the payment provider confirms it. When a request is queued, give the "
        "reference number and say when they will hear back.",
        owner="care-policy",
    ),
    Document(
        "CARE-FRAUD-INT",
        "Refund abuse signals (internal)",
        "# Refund abuse\nCARE-FRAUD-INT: Accounts flagged for refund abuse are routed to fraud "
        "operations. Never mention the review to the customer.",
        groups=frozenset({"fraud-ops"}),
        owner="fraud-ops",
    ),
]


def corpus() -> KnowledgeCorpus:
    chunks = [c for d in DOCS for c in chunk_document(d)]
    return KnowledgeCorpus(
        "care-policy",
        chunks,
        synonyms={"late": ["delivery", "shipment"], "refund": ["money back"]},
        refresh_sla="event-driven on policy publish",
    )


def builder() -> ContextBuilder:
    return ContextBuilder(
        corpus(),
        budget=Budget(policy=500, facts=300, history=300, tool_io=200),
        cache=SemanticCache(),
        min_coverage=0.2,
    )


def case_chunks(cases: list[dict[str, Any]]) -> list[Chunk]:
    return [
        Chunk(
            c["case_id"],
            c["case_id"],
            c["text"],
            title=f"CRM case {c['at']}",
            groups=frozenset(c.get("groups") or ["care"]),
            tenant=c.get("tenant"),
            kind="case",
        )
        for c in cases
    ]
