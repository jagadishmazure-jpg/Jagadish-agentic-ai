"""Loan origination system (LOS) document index behind MCP.

The classifier only ever *files* a document under a type or *queues* it for a processor.
Both are writes with idempotency keys (``classify:<doc_id>``) and dry-run by default, and
only scrubbed text metadata crosses the boundary (never the page text itself).
"""

from __future__ import annotations

from typing import Any

from shared.mcp_servers.kit import SorServer
from shared.resilience import Backoff
from shared.tools import ToolGateway, connect_servers

AGENT = "doc-classifier"
IDENTITY = "mi-doc-classifier"
ALLOW = {"los.file_document", "los.queue_review"}
Json = dict[str, Any]


class LosBackend:
    """In-memory LOS document index."""

    def __init__(self) -> None:
        self.filed: dict[str, Json] = {}
        self.review: dict[str, Json] = {}

    def file_document(self, record: Json) -> Json:
        self.filed[record["doc_id"]] = record
        return {"doc_id": record["doc_id"], "status": "filed", "doc_type": record["doc_type"]}

    def queue_review(self, record: Json) -> Json:
        self.review[record["doc_id"]] = record
        return {"doc_id": record["doc_id"], "status": "queued", "queue": "doc-review"}


def server(los: LosBackend) -> SorServer:
    srv = SorServer("los", "Loan origination system document index.", "LOS")

    @srv.write
    def file_document(
        loan_id: str,
        doc_id: str,
        doc_type: str,
        confidence: float,
        model_version: str,
        idempotency_key: str,
        dry_run: bool = True,
    ) -> Json:
        """File a document in the loan's e-folder under a document type."""
        rec = {
            "loan_id": loan_id,
            "doc_id": doc_id,
            "doc_type": doc_type,
            "confidence": confidence,
            "model_version": model_version,
        }
        return {"preview": rec} if dry_run else los.file_document(rec)

    @srv.write
    def queue_review(
        loan_id: str, doc_id: str, reason: str, idempotency_key: str, dry_run: bool = True
    ) -> Json:
        """Queue a document for a processor to classify by hand."""
        rec = {"loan_id": loan_id, "doc_id": doc_id, "reason": reason}
        return {"preview": rec} if dry_run else los.queue_review(rec)

    return srv


def build_gateway(los: LosBackend) -> ToolGateway:
    return ToolGateway(
        AGENT,
        IDENTITY,
        connect_servers({"los": server(los)}),
        ALLOW,
        error_types={"KeyError": KeyError},
        retry=Backoff(attempts=2, base_s=0.05),
        timeout_s=5.0,
    )
