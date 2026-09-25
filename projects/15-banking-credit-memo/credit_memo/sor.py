"""MCP servers (semantic layer, KYC screening, risk model, loan system) + gateways."""

from __future__ import annotations

from typing import Any

from credit_memo import semantic
from credit_memo.systems import Systems
from shared.mcp_servers.kit import SorServer
from shared.resilience import Backoff
from shared.tools import ToolGateway, connect_servers

Json = dict[str, Any]


def servers(s: Systems) -> dict[str, SorServer]:
    sem = SorServer(
        "semantic", "Governed semantic layer over the gold credit mart (no SQL).", "Semantic layer"
    )

    @sem.read
    def get_measure(name: str, grain: str, filters: Json, dry_run: bool = True) -> Json:
        """Governed measure by name/grain/filters; dry_run returns the compiled plan."""
        return semantic.get_measure(name, grain, filters, dry_run)

    kyc = SorServer("kyc", "Sanctions / PEP screening.", "KYC screening")

    @kyc.read
    def screen(names: list[str]) -> Json:
        """Screen names against sanctions/PEP lists."""
        return s.screen(names)

    risk = SorServer("risk_model", "Existing PD / rating model endpoint.", "Risk model")

    @risk.read
    def score(borrower_id: str) -> Json:
        """Probability of default and rating grade from the validated model."""
        return s.score(borrower_id)

    loans = SorServer("loan_system", "Loan origination / limits system.", "Loan system")

    @loans.write
    def set_credit_limit(
        borrower_id: str,
        amount: float,
        approvals: list[str],
        idempotency_key: str,
        dry_run: bool = True,
    ) -> Json:
        """Book a credit limit (money/limit tool: dual control enforced server-side)."""
        if dry_run:
            return {"preview": amount}
        return s.set_credit_limit(borrower_id, amount, approvals)

    return {"semantic": sem, "kyc": kyc, "risk_model": risk, "loan_system": loans}


def gateways(s: Systems) -> dict[str, ToolGateway]:
    conns = connect_servers(servers(s))
    kw = {
        "error_types": {
            "SemanticError": semantic.SemanticError,
            "KeyError": KeyError,
            "PermissionError": PermissionError,
        },
        "retry": Backoff(attempts=2, base_s=0.05),
        "timeout_s": 5.0,
    }
    return {
        "reader": ToolGateway(
            "credit-memo",
            "mi-credit-reader",
            conns,
            {"semantic.get_measure", "kyc.screen", "risk_model.score"},
            **kw,
        ),
        "booker": ToolGateway(
            "credit-memo", "mi-limit-booker", conns, {"loan_system.set_credit_limit"}, **kw
        ),
    }
