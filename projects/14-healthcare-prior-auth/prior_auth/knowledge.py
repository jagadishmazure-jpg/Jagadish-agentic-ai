"""Knowledge plane: plan medical policies with plan-year validity and per-plan ACL.

* Temporal: each policy edition is valid for its plan year; retrieval runs as-of the date of
  service (2025 lumbar-MRI criteria differ from 2026).
* ACL: plan-specific policies carry ``plan:<id>`` groups; the agent's principal holds only the
  member's plan group, so a Gold PPO request never sees Silver HMO referral rules. The UM
  medical-director guidance is visible to that role only.
* PHI: the clinical note is redacted (names, MRN, DOB, SSN, phone) before it is packed as
  facts; the shared sanitizer runs again inside the builder.
"""

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

ALL_PLANS = frozenset({"plan:gold-ppo", "plan:silver-hmo"})
Y25 = {"valid_from": date(2025, 1, 1), "valid_to": date(2025, 12, 31), "version": "2025"}
Y26 = {"valid_from": date(2026, 1, 1), "valid_to": date(2026, 12, 31), "version": "2026"}


def _doc(doc_id: str, title: str, body: str, groups=ALL_PLANS, **kw) -> Document:
    return Document(
        doc_id, title, f"# {title}\n{doc_id}: {body}", groups=groups, owner="medical-policy", **kw
    )


DOCS = [
    _doc(
        "MP-LSPINE-MRI-2025",
        "Lumbar spine MRI (plan year 2025)",
        "MRI of the lumbar spine (CPT 72148) for low back pain is medically necessary after at "
        "least 6 weeks of documented conservative therapy, or sooner when red flags are "
        "present (progressive neurological deficit, cauda equina signs, suspected infection "
        "or malignancy).",
        **Y25,
    ),
    _doc(
        "MP-LSPINE-MRI-2026",
        "Lumbar spine MRI (plan year 2026)",
        "MRI of the lumbar spine (CPT 72148) for low back pain is medically necessary after at "
        "least 4 weeks of documented conservative therapy, or sooner when red flags are "
        "present (progressive neurological deficit, cauda equina signs, suspected infection "
        "or malignancy).",
        **Y26,
    ),
    _doc(
        "MP-KNEE-SCOPE-2026",
        "Knee arthroscopy (plan year 2026)",
        "Knee arthroscopy (CPT 29881) requires mechanical symptoms such as locking or catching "
        "and at least 6 weeks of failed conservative therapy.",
        **Y26,
    ),
    _doc(
        "MP-SILVER-REFERRAL-2026",
        "Silver HMO advanced imaging referral (plan year 2026)",
        "Advanced imaging for Silver HMO members requires a primary care referral on file.",
        groups=frozenset({"plan:silver-hmo"}),
        **Y26,
    ),
    _doc(
        "MP-GOLD-SITE-2026",
        "Gold PPO site of care (plan year 2026)",
        "Gold PPO members may use any in-network imaging site; freestanding centers are preferred.",
        groups=frozenset({"plan:gold-ppo"}),
        **Y26,
    ),
    _doc(
        "UM-MD-GUIDE-INT",
        "UM medical director guidance (internal)",
        "Peer-to-peer review is offered before any adverse determination.",
        groups=frozenset({"um-medical-director"}),
    ),
]


def corpus() -> KnowledgeCorpus:
    return KnowledgeCorpus(
        "medical-policies",
        [c for d in DOCS for c in chunk_document(d)],
        synonyms={
            "mri": ["imaging", "72148"],
            "arthroscopy": ["29881", "scope"],
            "pt": ["physical therapy", "conservative therapy"],
        },
        refresh_sla="plan-year publish + mid-year bulletins within 24h",
    )


def principal(plan: str) -> Principal:
    return Principal.of("mi-pa-agent", f"plan:{plan}")


def builder() -> ContextBuilder:
    return ContextBuilder(
        corpus(),
        budget=Budget(policy=900, facts=500, history=0, tool_io=200),
        cache=SemanticCache(),
    )
