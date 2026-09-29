"""Credit policy corpus for the policy agent: editions by effective date + ACL.

The DTI rule has two editions (2025 and 2026). Retrieval is as-of the application date, so a
file taken in November 2025 is judged by the 2025 ceiling even though the 2026 edition is more
generous. Credit-committee minutes are restricted to the committee group and are trimmed before
ranking, so no underwriting agent can ever cite them.
"""

from __future__ import annotations

from datetime import date

from shared.context import (
    Budget,
    ContextBuilder,
    Document,
    KnowledgeCorpus,
    Principal,
    chunk_document,
)

UNDERWRITING = frozenset({"underwriting"})
Y25 = {"valid_from": date(2025, 1, 1), "valid_to": date(2025, 12, 31), "version": "2025"}
Y26 = {"valid_from": date(2026, 1, 1), "version": "2026"}


def _doc(doc_id: str, title: str, body: str, groups=UNDERWRITING, **kw) -> Document:
    return Document(
        doc_id, title, f"# {title}\n{doc_id}: {body}", groups=groups, owner="credit-policy", **kw
    )


DOCS = [
    _doc(
        "CP-DTI-2025",
        "Debt-to-income exceptions (2025 edition)",
        "Base maximum debt-to-income ratio (DTI) 43%. An underwriter may grant a DTI exception "
        "up to 48% with at least two compensating factors, conditioned on verified reserves and "
        "employment reverification. DTI above 48% and up to 53% is referred to credit committee; "
        "above 53% the exception is declined.",
        **Y25,
    ),
    _doc(
        "CP-DTI-2026",
        "Debt-to-income exceptions (2026 edition)",
        "Base maximum debt-to-income ratio (DTI) 43%. An underwriter may grant a DTI exception "
        "up to 50% with at least two compensating factors, conditioned on verified reserves and "
        "employment reverification. DTI above 50% and up to 55% is referred to credit committee; "
        "above 55% the exception is declined.",
        **Y26,
    ),
    _doc(
        "CP-LTV-2026",
        "Loan-to-value exceptions",
        "Base maximum loan-to-value ratio (LTV) 80%. An LTV exception up to 90% needs one "
        "compensating factor and mortgage insurance. LTV above 90% is declined.",
    ),
    _doc(
        "CP-FICO-2026",
        "Credit score exceptions",
        "Minimum credit score 660. A credit score exception down to 620 needs two compensating "
        "factors and a no-new-credit attestation before closing. Below 620 is declined.",
    ),
    _doc(
        "CP-COMP-2026",
        "Compensating factors",
        "Recognised compensating factors: reserves of six months or more, credit score 740 or "
        "higher, employment tenure of five years or more, LTV 70% or lower, DTI 36% or lower. A "
        "metric never compensates for its own exception.",
    ),
    _doc(
        "CP-AUTH-2026",
        "Delegated authority for exceptions",
        "An underwriter may approve at most two exceptions on one file; two exceptions add a "
        "senior underwriter sign-off condition. Three or more exceptions go to credit committee.",
    ),
    _doc(
        "CP-DOCS-2026",
        "Missing documents",
        "No exception decision is made without an appraisal. When the appraisal has not been "
        "received the file is pended with the condition to obtain the appraisal.",
    ),
    _doc(
        "CC-MINUTES-2026-03",
        "Credit committee minutes (restricted)",
        "Committee discussion of individual referred files. Restricted to committee members.",
        groups=frozenset({"credit-committee"}),
    ),
]

# topic -> retrieval query used by the policy agent
QUERIES = {
    "dti": "debt-to-income DTI exception ceiling committee",
    "ltv": "loan-to-value LTV exception mortgage insurance",
    "fico": "credit score exception minimum attestation",
    "comp": "compensating factors reserves tenure",
    "auth": "delegated authority number of exceptions senior sign-off",
    "docs": "missing documents appraisal pended",
}


def corpus() -> KnowledgeCorpus:
    return KnowledgeCorpus(
        "credit-policy",
        [c for d in DOCS for c in chunk_document(d)],
        synonyms={"dti": ["debt-to-income"], "ltv": ["loan-to-value"]},
        refresh_sla="on credit policy committee approval",
    )


def principal() -> Principal:
    return Principal.of("mi-exception-policy-agent", "underwriting")


def builder() -> ContextBuilder:
    return ContextBuilder(corpus(), budget=Budget(policy=400, facts=0, history=0, tool_io=0))
