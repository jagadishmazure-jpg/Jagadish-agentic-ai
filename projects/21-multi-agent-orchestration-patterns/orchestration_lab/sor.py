"""Systems of record behind MCP (loan origination system, credit bureau) + scoped gateways.

Identities (least privilege):

* ``mi-exception-researcher`` / ``mi-exception-analyst``: read the loan file, appraisal and
  credit summary (the analyst reads for itself only when no researcher ran first, e.g. in the
  concurrent pattern).
* ``mi-exception-filer``: the orchestrator's identity; the only one that may file the memo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from orchestration_lab.domain import BORROWER_NOTES, LOANS
from shared.mcp_servers.kit import SorServer
from shared.resilience import Backoff
from shared.tools import ToolGateway, connect_servers

Json = dict[str, Any]
READS = {
    "loan_system.get_loan_file",
    "loan_system.get_appraisal",
    "credit_bureau.get_credit_summary",
}


@dataclass
class LoanSystems:
    loans: dict[str, dict[str, Any]] = field(
        default_factory=lambda: {k: dict(v) for k, v in LOANS.items()}
    )
    notes: dict[str, str] = field(default_factory=lambda: dict(BORROWER_NOTES))
    filed: list[Json] = field(default_factory=list)

    def loan(self, loan_id: str) -> dict[str, Any]:
        if loan_id not in self.loans:
            raise KeyError(f"unknown loan {loan_id}")
        return self.loans[loan_id]


def servers(s: LoanSystems) -> dict[str, SorServer]:
    los = SorServer("loan_system", "Loan origination system (mock).", "Loan origination system")

    @los.read
    def get_loan_file(loan_id: str) -> Json:
        """Application: date, amount, income, monthly debts, reserves, employment, notes."""
        f = s.loan(loan_id)
        keys = ("app_date", "amount", "income", "debts", "reserves", "employment")
        return {"loan_id": loan_id, **{k: f[k] for k in keys}, "note": s.notes.get(loan_id, "")}

    @los.read
    def get_appraisal(loan_id: str) -> Json:
        """Appraised value, or status=not_received."""
        v = s.loan(loan_id)["value"]
        return {"loan_id": loan_id, "status": "received" if v else "not_received", "value": v}

    @los.write
    def file_exception_memo(
        loan_id: str, decision: str, memo: str, idempotency_key: str, dry_run: bool = True
    ) -> Json:
        """File the exception memo on the loan (does not fund or change the loan)."""
        rec = {"loan_id": loan_id, "decision": decision, "memo": memo}
        if dry_run:
            return {"preview": rec}
        s.filed.append(rec)
        return {"filed": True, "memo_id": f"MEMO-{loan_id}-{len(s.filed)}"}

    bureau = SorServer("credit_bureau", "Tri-merge credit summary (mock).", "Credit bureau")

    @bureau.read
    def get_credit_summary(loan_id: str) -> Json:
        """Representative credit score."""
        return {"loan_id": loan_id, "fico": s.loan(loan_id)["fico"]}

    return {"loan_system": los, "credit_bureau": bureau}


def gateways(s: LoanSystems) -> dict[str, ToolGateway]:
    conns = connect_servers(servers(s))
    kw = {"error_types": {"KeyError": KeyError}, "retry": Backoff(attempts=2, base_s=0.05)}
    return {
        "researcher": ToolGateway(
            "exception-researcher", "mi-exception-researcher", conns, set(READS), **kw
        ),
        "analyst": ToolGateway(
            "exception-analyst", "mi-exception-analyst", conns, set(READS), **kw
        ),
        "filer": ToolGateway(
            "exception-orchestrator",
            "mi-exception-filer",
            conns,
            {"loan_system.file_exception_memo"},
            **kw,
        ),
    }
