"""Refund policy as a knowledge product: chunked by rule, with ACL and temporal validity,
served through the shared context builder (as-of the delivery date of the order)."""

from __future__ import annotations

from datetime import date

from refund_agent.policy import POLICY
from shared.context import Budget, Chunk, ContextBuilder, KnowledgeCorpus, Principal

PRINCIPAL = Principal.of("mi-refund-agent", "support", "refund-agent")
TOPICS = {
    "RP-1": "verified customer identity email",
    "RP-2": "refund window days of delivery",
    "RP-3": "refunded at most once",
    "RP-4": "gift cards final-sale non-refundable",
    "RP-5": "under $50 approved automatically",
    "RP-6": "$50 or more require human approval",
    "RP-7": "fraud indicators fraud team",
}
CURRENT_FROM = date(2026, 1, 1)


def corpus() -> KnowledgeCorpus:
    chunks = [
        Chunk(
            rid,
            "REFUND-POLICY-2026",
            text,
            title="Refund policy",
            heading_path=("Refunds", rid),
            parent_id="REFUND-POLICY-2026",
            valid_from=CURRENT_FROM,
            version="2026.1",
            # the fraud rule is internal: not visible to customer-facing Q&A agents
            groups=frozenset({"fraud-ops", "refund-agent"}) if rid == "RP-7" else frozenset({"*"}),
        )
        for rid, text in POLICY.items()
    ]
    # Superseded 2025 edition: only retrieved for events dated in 2025.
    chunks.append(
        Chunk(
            "RP-2@2025",
            "REFUND-POLICY-2025",
            "Refunds are available within 14 days of delivery.",
            title="Refund policy (2025)",
            heading_path=("Refunds", "RP-2"),
            valid_from=date(2025, 1, 1),
            valid_to=date(2025, 12, 31),
            version="2025.3",
        )
    )
    return KnowledgeCorpus(
        "refund-policy", chunks, owner="Jagadish Meduri", refresh_sla="on publish (event-driven)"
    )


def builder() -> ContextBuilder:
    return ContextBuilder(corpus(), budget=Budget(policy=400, facts=150, history=0, tool_io=100))


def policy_citations(
    b: ContextBuilder, rule_ids: list[str], as_of: date
) -> tuple[list[str], list[str]]:
    """Retrieve the policy text in force on ``as_of`` for the rules a decision used.
    Returns (citations "RP-x: text", missing rule ids). Raises RetrievalError if down."""
    query = " ".join(TOPICS[r] for r in rule_ids)
    bundle = b.build(query, PRINCIPAL, as_of=as_of, k=len(TOPICS))
    # use the sanitized, packed text - never raw chunk text
    found = {e.source_id.split("@")[0]: e.text for e in bundle.packed.items}
    cites = [f"{r}: {found[r]}" for r in rule_ids if r in found]
    return cites, [r for r in rule_ids if r not in found]
