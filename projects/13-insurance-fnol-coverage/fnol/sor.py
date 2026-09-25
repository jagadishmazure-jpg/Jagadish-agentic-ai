"""MCP servers for the FNOL systems of record + the two gateway identities.

* ``mi-fnol-reader``: docintel.analyze_document, policy_admin.get_policy, fraud_ml.score_claim
* ``mi-claims-writer``: claims.open_claim / set_reserve / issue_payment / queue_document
"""

from __future__ import annotations

from typing import Any

from fnol import ocr
from fnol.systems import Systems
from shared.mcp_servers.kit import SorServer
from shared.resilience import Backoff
from shared.tools import ToolGateway, connect_servers

Json = dict[str, Any]


def servers(s: Systems) -> dict[str, SorServer]:
    doc = SorServer(
        "docintel", "Document extraction over scanned claim packets.", "Document Intelligence"
    )

    @doc.read
    def analyze_document(document_id: str) -> Json:
        """Extract field-value pairs with confidence from a scanned FNOL packet."""
        return ocr.analyze(s.packets[document_id])

    pol = SorServer("policy_admin", "Policy administration system.", "Policy admin")

    @pol.read
    def get_policy(policy_number: str) -> Json:
        """Policy terms: form, edition, jurisdiction, term, limits, deductible."""
        return s.policies[policy_number]

    fraud = SorServer("fraud_ml", "Fraud scoring model endpoint.", "Fraud ML endpoint")

    @fraud.read
    def score_claim(policy_number: str, loss_date: str, reported_date: str, amount: float) -> Json:
        """Model-computed fraud risk score, band and reasons (internal use only)."""
        return s.score_claim(policy_number, loss_date, reported_date, amount)

    claims = SorServer("claims", "Claims system (Guidewire-like).", "Claims system")

    @claims.write
    def open_claim(fnol: Json, idempotency_key: str, dry_run: bool = True) -> Json:
        """Register the FNOL as a claim."""
        return {"preview": fnol} if dry_run else s.open_claim(fnol)

    @claims.write
    def set_reserve(
        claim_id: str, amount: float, approver: str, idempotency_key: str, dry_run: bool = True
    ) -> Json:
        """Set the indemnity reserve (requires an adjuster approver)."""
        return {"preview": amount} if dry_run else s.set_reserve(claim_id, amount, approver)

    @claims.write
    def issue_payment(
        claim_id: str, amount: float, approver: str, idempotency_key: str, dry_run: bool = True
    ) -> Json:
        """Issue an indemnity payment (requires an adjuster approver)."""
        return {"preview": amount} if dry_run else s.issue_payment(claim_id, amount, approver)

    @claims.write
    def queue_document(
        document_id: str, reason: str, idempotency_key: str, dry_run: bool = True
    ) -> Json:
        """Send a packet to the manual indexing queue."""
        return {"preview": reason} if dry_run else s.queue_document(document_id, reason)

    return {"docintel": doc, "policy_admin": pol, "fraud_ml": fraud, "claims": claims}


def gateways(s: Systems) -> dict[str, ToolGateway]:
    conns = connect_servers(servers(s))
    kw = {
        "error_types": {"KeyError": KeyError},
        "retry": Backoff(attempts=2, base_s=0.05),
        "timeout_s": 5.0,
    }
    reader = ToolGateway(
        "fnol-graph",
        "mi-fnol-reader",
        conns,
        {"docintel.analyze_document", "policy_admin.get_policy", "fraud_ml.score_claim"},
        **kw,
    )
    writer = ToolGateway(
        "fnol-graph",
        "mi-claims-writer",
        conns,
        {
            "claims.open_claim",
            "claims.set_reserve",
            "claims.issue_payment",
            "claims.queue_document",
        },
        **kw,
    )
    return {"reader": reader, "writer": writer}
