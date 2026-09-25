"""Legal playbook as a knowledge product on the shared context builder.

The deterministic rules engine (red flags, required terms, guardrails) stays in code - it is
the control. What the reviewer model *reads* (standard position + approved redline per clause
type) is retrieved per clause through the shared ContextBuilder:

* hybrid retrieval over clause heading + text, filtered to the clause's playbook entry;
* ACL - senior-counsel fallback positions are visible only to ``legal-senior``; the review
  agent runs as ``legal-ops`` and can never leak a fallback concession into a redline;
* sanitised text + typed errors (``RetrievalUnavailableError`` -> rules-only degrade).
"""

from __future__ import annotations

from typing import Any

from contract_review.library import LIBRARY
from shared.context import Chunk, ContextBuilder, KnowledgeCorpus, Principal, sanitize

LEGAL_OPS = Principal.of("mi-contract-review", "legal-ops")
SENIOR_COUNSEL = Principal.of("senior-counsel", "legal-ops", "legal-senior")
FALLBACKS = {
    "limitation_of_liability": "Fallback (senior counsel only): accept a cap of 6 months of "
    "fees if the customer insists.",
    "auto_renewal": "Fallback (senior counsel only): accept 60 days' non-renewal notice.",
}


def _cid(ctype: str) -> str:
    return "PB-" + ctype.upper().replace("_", "-")


def corpus() -> KnowledgeCorpus:
    chunks = []
    for ctype, spec in LIBRARY.items():
        words = " ".join(spec["keywords"])
        text = f"Standard: {spec['standard']}"
        if spec["redline"]:
            text += f" Approved redline: {spec['redline']}"
        chunks.append(
            Chunk(
                _cid(ctype),
                "legal-playbook",
                f"{text} Keywords: {words}.",
                title=ctype.replace("_", " "),
                heading_path=("standard",),
                parent_id="legal-playbook",
                groups=frozenset({"legal-ops"}),
                kind="playbook",
                meta={"clause_type": ctype},
            )
        )
    for ctype, text in FALLBACKS.items():
        chunks.append(
            Chunk(
                f"{_cid(ctype)}-FALLBACK",
                "legal-playbook",
                f"{text} Keywords: {' '.join(LIBRARY[ctype]['keywords'])}.",
                title=f"{ctype.replace('_', ' ')} fallback",
                heading_path=("fallback",),
                parent_id=_cid(ctype),
                groups=frozenset({"legal-senior"}),
                kind="playbook",
                meta={"clause_type": ctype},
            )
        )
    return KnowledgeCorpus("legal-playbook", chunks, refresh_sla="on playbook approval")


def builder() -> ContextBuilder:
    return ContextBuilder(corpus())


def playbook_context(
    kb: ContextBuilder, clauses: list[dict[str, Any]], principal: Principal = LEGAL_OPS
) -> dict[str, dict[str, str]]:
    """{clause_type: {"id", "text"}} for the clause types present, retrieved per clause."""
    out: dict[str, dict[str, str]] = {}
    for c in clauses:
        ctype = c.get("type")
        if ctype not in LIBRARY or ctype in out:
            continue
        query = f"{ctype.replace('_', ' ')} {c['heading']} {c['text']}"
        hits, *_ = kb.retrieve(query, principal, k=6, kinds=["playbook"])
        for h in hits:
            if h.chunk.meta.get("clause_type") == ctype:
                out[ctype] = {
                    "id": h.chunk_id,
                    "text": sanitize(h.chunk.text, redact_pii=False).text,
                }
                break
    return out
