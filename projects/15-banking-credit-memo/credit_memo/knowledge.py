"""Credit policy corpus: editions by effective date (as-of the application date) + ACL."""

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

CREDIT = frozenset({"credit-risk"})
P25 = {"valid_from": date(2025, 1, 1), "valid_to": date(2025, 12, 31), "version": "2025"}
P26 = {"valid_from": date(2026, 1, 1), "version": "2026"}


def _doc(doc_id: str, title: str, body: str, groups=CREDIT, **kw) -> Document:
    return Document(
        doc_id, title, f"# {title}\n{doc_id}: {body}", groups=groups, owner="credit-policy", **kw
    )


DOCS = [
    _doc(
        "CP-LEVERAGE-2025",
        "Leverage and coverage limits (2025)",
        "Maximum senior leverage (total debt / EBITDA): grades BBB- and better 3.75x; BB+ to "
        "BB- 3.0x; B+ and below 2.25x. Minimum debt service coverage ratio 1.20x.",
        **P25,
    ),
    _doc(
        "CP-LEVERAGE-2026",
        "Leverage and coverage limits (2026)",
        "Maximum senior leverage (total debt / EBITDA): grades BBB- and better 4.0x; BB+ to "
        "BB- 3.25x; B+ and below 2.5x. Minimum debt service coverage ratio 1.25x.",
        **P26,
    ),
    _doc(
        "CP-KYC-1",
        "Know your customer",
        "Every beneficial owner holding 25% or more must be identified and screened before a "
        "credit memo is prepared. Undisclosed trust beneficiaries or a screening match stop "
        "the application.",
    ),
    _doc(
        "CP-DUAL-1",
        "Dual control",
        "Credit limits are booked only with two distinct approvers; the second approver must "
        "be a credit officer.",
    ),
    _doc(
        "SA-WATCHLIST-INT",
        "Special assets watchlist (internal)",
        "Borrowers on the watchlist require special-assets sign-off.",
        groups=frozenset({"special-assets"}),
    ),
]

POLICY_LIMITS = {  # (edition, grade band) -> max leverage; min DSCR per edition
    "2025": {"ig": 3.75, "bb": 3.0, "b": 2.25, "min_dscr": 1.20},
    "2026": {"ig": 4.0, "bb": 3.25, "b": 2.5, "min_dscr": 1.25},
}


def band(grade: str) -> str:
    if grade.startswith(("A", "BBB")):
        return "ig"
    return "bb" if grade.startswith("BB") else "b"


def corpus() -> KnowledgeCorpus:
    return KnowledgeCorpus(
        "credit-policy",
        [c for d in DOCS for c in chunk_document(d)],
        synonyms={"leverage": ["debt", "ebitda"], "dscr": ["coverage"]},
        refresh_sla="on credit committee approval",
    )


def principal() -> Principal:
    return Principal.of("mi-credit-memo-agent", "credit-risk")


def builder() -> ContextBuilder:
    return ContextBuilder(
        corpus(),
        budget=Budget(policy=800, facts=600, history=0, tool_io=300),
        cache=SemanticCache(),
    )
