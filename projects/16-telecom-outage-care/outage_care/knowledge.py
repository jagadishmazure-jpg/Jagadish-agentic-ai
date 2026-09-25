"""Tariff corpus (plan editions as-of the bill period, proration, equipment, outage credits)
and the NOC runbook (ACL: noc only)."""

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

EVERYONE = frozenset({"care", "noc"})


def _doc(doc_id: str, title: str, body: str, groups=EVERYONE, **kw) -> Document:
    return Document(
        doc_id, title, f"# {title}\n{doc_id}: {body}", groups=groups, owner="product-pricing", **kw
    )


DOCS = [
    _doc(
        "TAR-FIBER-500-2025",
        "Fiber 500 tariff (2025)",
        "Fiber 500 plan monthly charge 60.00 billed in advance.",
        valid_from=date(2025, 1, 1),
        valid_to=date(2025, 12, 31),
        version="2025",
    ),
    _doc(
        "TAR-FIBER-500-2026",
        "Fiber 500 tariff (2026)",
        "Fiber 500 plan monthly charge 65.00 billed in advance.",
        valid_from=date(2026, 1, 1),
        version="2026",
    ),
    _doc(
        "TAR-MOBILE-UNL-2026",
        "Mobile Unlimited tariff (2026)",
        "Mobile Unlimited plan monthly charge 55.00 billed in advance.",
        valid_from=date(2026, 1, 1),
        version="2026",
    ),
    _doc(
        "TAR-PRORATION-1",
        "Plan change proration",
        "When a plan changes mid-cycle, the price difference is charged for the remaining "
        "days of the cycle as a one-time proration line.",
    ),
    _doc(
        "TAR-EQUIP-1",
        "Equipment rental",
        "Rented WiFi routers are billed monthly as an equipment rental line.",
    ),
    _doc(
        "TAR-OUTAGE-CREDIT-1",
        "Outage credits",
        "A confirmed network outage lasting more than 24 hours earns a credit of one day of the "
        "plan charge per full day of outage, applied on the next bill.",
    ),
    _doc(
        "NOC-RUNBOOK-INT",
        "NOC runbook (internal)",
        "Aggregation switch failures: reroute via the ring before dispatching.",
        groups=frozenset({"noc"}),
    ),
]
PLAN_TARIFF = {"Fiber 500": "TAR-FIBER-500", "Mobile Unlimited": "TAR-MOBILE-UNL"}


def corpus() -> KnowledgeCorpus:
    return KnowledgeCorpus(
        "tariffs",
        [c for d in DOCS for c in chunk_document(d)],
        synonyms={"proration": ["partial", "prorated"], "rental": ["equipment", "router"]},
        refresh_sla="on tariff publication",
    )


def principal(channel: str) -> Principal:
    return Principal.of(f"mi-{channel}-assistant", channel)


def builder() -> ContextBuilder:
    return ContextBuilder(
        corpus(),
        budget=Budget(policy=700, facts=400, history=0, tool_io=300),
        cache=SemanticCache(),
    )
