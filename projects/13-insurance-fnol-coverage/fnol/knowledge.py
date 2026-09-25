"""Knowledge plane: homeowners policy forms by edition + state amendatory endorsements.

* Temporal: each form provision carries the validity of its **edition**. Retrieval runs as-of
  the edition date printed on the policy (a 2019-edition policy renewed in 2025 still reads the
  2019 wording), not today's date.
* Jurisdiction: state amendatory endorsements carry the state in the tenant dimension of the
  ACL, so a Texas claim can never retrieve California wording (and vice versa).
* ACL: SIU referral guidelines are visible to the ``siu`` group only.
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

EDITION_DATES = {"2019": date(2019, 6, 1), "2023": date(2023, 1, 1)}
E19 = {"valid_from": date(2019, 6, 1), "valid_to": date(2022, 12, 31), "version": "2019"}
E23 = {"valid_from": date(2023, 1, 1), "version": "2023"}


def _doc(doc_id: str, title: str, body: str, **kw) -> Document:
    return Document(doc_id, title, f"# {title}\n{doc_id}: {body}", owner="product-forms", **kw)


DOCS = [
    _doc(
        "HO3-2019-WATER",
        "HO3 2019 water damage",
        "Sudden and accidental discharge of water or steam from a plumbing system or household "
        "appliance is covered. Continuous or repeated seepage or leakage of water over a "
        "period of 30 days or more is excluded.",
        **E19,
    ),
    _doc(
        "HO3-2023-WATER",
        "HO3 2023 water damage",
        "Sudden and accidental discharge of water or steam from a plumbing system or household "
        "appliance is covered. Continuous or repeated seepage or leakage of water over a "
        "period of 14 days or more is excluded.",
        **E23,
    ),
    _doc(
        "HO3-2019-PERILS",
        "HO3 2019 named perils",
        "Fire or lightning, windstorm or hail, and theft are covered perils for the dwelling "
        "and personal property.",
        **E19,
    ),
    _doc(
        "HO3-2023-PERILS",
        "HO3 2023 named perils",
        "Fire or lightning, windstorm or hail, and theft are covered perils for the dwelling "
        "and personal property. Wind-driven rain entering through a storm opening is covered.",
        **E23,
    ),
    _doc(
        "HO3-FLOOD",
        "HO3 flood exclusion",
        "Flood, surface water, overflow of a body of water and storm surge are excluded under "
        "every edition; flood cover requires a separate flood policy.",
    ),
    _doc(
        "TX-AMEND-2019-MOLD",
        "Texas amendatory endorsement 2019 - mold",
        "Mold remediation resulting from a covered water loss is limited to 5000 per loss.",
        tenant="TX",
        **E19,
    ),
    _doc(
        "TX-AMEND-2023-MOLD",
        "Texas amendatory endorsement 2023 - mold",
        "Mold remediation resulting from a covered water loss is limited to 8000 per loss.",
        tenant="TX",
        **E23,
    ),
    _doc(
        "CA-AMEND-2023-MOLD",
        "California amendatory endorsement 2023 - mold",
        "Mold remediation resulting from a covered water loss is limited to 10000 per loss.",
        tenant="CA",
        **E23,
    ),
    _doc(
        "CLAIMS-COMMS-1",
        "Claimant communication standard",
        "Acknowledge every claim with its reference. Explain coverage decisions by citing the "
        "policy provision. Never mention internal reviews, investigations or risk scores to "
        "the claimant.",
    ),
    _doc(
        "SIU-GUIDE-INT",
        "SIU referral guidelines (internal)",
        "Refer claims with a high model risk band to the special investigations unit before "
        "any payment. Reserves may be set; payments are held.",
        groups=frozenset({"siu"}),
    ),
]


def corpus() -> KnowledgeCorpus:
    chunks = [c for d in DOCS for c in chunk_document(d)]
    return KnowledgeCorpus(
        "policy-forms",
        chunks,
        synonyms={
            "leak": ["seepage", "leakage"],
            "mold": ["mould", "remediation"],
            "wind": ["windstorm", "hail"],
            "stolen": ["theft"],
        },
        refresh_sla="on form filing approval",
    )


def principal(jurisdiction: str) -> Principal:
    return Principal.of("mi-fnol-agent", "claims", tenant=jurisdiction)


def builder() -> ContextBuilder:
    return ContextBuilder(
        corpus(),
        budget=Budget(policy=900, facts=300, history=0, tool_io=200),
        cache=SemanticCache(),
    )
