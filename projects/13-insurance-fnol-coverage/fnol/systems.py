"""Mock systems of record: scanned-packet store, policy admin, fraud ML endpoint, claims."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from datetime import date
from typing import Any

PACKET = """=== FNOL packet (scanned) ===
Policy Number: {policy}
Insured Name: {insured}
Date of Loss: {loss}
Date Reported: {reported}
Loss Location: {location}
Cause of Loss: {cause}
Description: {description}
Estimated Amount: {estimate}
{extra}"""


def packet(
    policy: str,
    description: str,
    estimate: float,
    *,
    cause: str = "water",
    loss: str = "2026-08-14",
    reported: str = "2026-08-16",
    insured: str = "Maria Lopez",
    location: str = "12 Elm St, Austin TX",
    extra: str = "",
) -> str:
    return PACKET.format(
        policy=policy,
        insured=insured,
        loss=loss,
        reported=reported,
        location=location,
        cause=cause,
        description=description,
        estimate=estimate,
        extra=extra,
    )


def _policy(
    number: str,
    edition: str,
    state: str,
    eff: str,
    exp: str,
    *,
    limit: float = 350000,
    deductible: float = 1000,
    inception: str = "2021-03-01",
    prior_claims: int = 0,
    insured: str = "Maria Lopez",
) -> dict[str, Any]:
    return {
        "policy_number": number,
        "form": "HO3",
        "edition": edition,
        "jurisdiction": state,
        "effective": eff,
        "expires": exp,
        "dwelling_limit": limit,
        "deductible": deductible,
        "inception": inception,
        "prior_claims_3y": prior_claims,
        "insured": insured,
    }


POLICIES = [
    _policy("HO-TX-1001", "2023", "TX", "2026-03-01", "2027-03-01"),
    _policy(
        "HO-TX-2002", "2019", "TX", "2025-11-01", "2026-11-01", deductible=2500, insured="Dev Patel"
    ),
    _policy(
        "HO-CA-3003", "2023", "CA", "2026-01-15", "2027-01-15", deductible=1500, insured="Lena Park"
    ),
    _policy(
        "HO-TX-4004",
        "2023",
        "TX",
        "2026-07-25",
        "2027-07-25",
        inception="2026-07-25",
        prior_claims=2,
        insured="Rick Moss",
    ),
    _policy("HO-TX-5005", "2023", "TX", "2025-06-30", "2026-06-30", insured="Ana Ruiz"),
    _policy(
        "HO-TX-6006", "2023", "TX", "2026-02-01", "2027-02-01", limit=40000, insured="Sam Cole"
    ),
]


@dataclass
class Systems:
    packets: dict[str, str] = field(default_factory=dict)
    policies: dict[str, dict[str, Any]] = field(default_factory=dict)
    claims: dict[str, dict[str, Any]] = field(default_factory=dict)
    reserves: list[dict[str, Any]] = field(default_factory=list)
    payments: list[dict[str, Any]] = field(default_factory=list)
    queue: list[dict[str, Any]] = field(default_factory=list)
    _ids: Any = field(default_factory=lambda: itertools.count(1))

    # --------------------------------------------------------------- fraud ML endpoint
    def score_claim(
        self, policy_number: str, loss_date: str, reported_date: str, amount: float
    ) -> dict[str, Any]:
        """Stand-in for a deployed fraud model (e.g. an Azure ML online endpoint). The agent
        only reads the score; it never computes or overrides it."""
        p = self.policies[policy_number]
        loss = date.fromisoformat(loss_date)
        reasons, score = [], 0.05
        if (loss - date.fromisoformat(p["inception"])).days < 30:
            score += 0.4
            reasons.append("loss within 30 days of inception")
        if p["prior_claims_3y"] >= 2:
            score += 0.3
            reasons.append("2+ prior claims in 3 years")
        if (date.fromisoformat(reported_date) - loss).days > 30:
            score += 0.2
            reasons.append("reported more than 30 days after loss")
        if amount > 0.8 * p["dwelling_limit"]:
            score += 0.15
            reasons.append("amount near the limit")
        score = round(min(score, 0.99), 2)
        band = "high" if score >= 0.7 else "medium" if score >= 0.4 else "low"
        return {
            "score": score,
            "band": band,
            "reasons": reasons,
            "model_version": "fraud-gbm-2026.07",
        }

    # --------------------------------------------------------------- claims system
    def open_claim(self, fnol: dict[str, Any]) -> dict[str, Any]:
        cid = f"CLM-{next(self._ids):05d}"
        self.claims[cid] = {"claim_id": cid, **fnol, "status": "open"}
        return {"claim_id": cid}

    def set_reserve(self, claim_id: str, amount: float, approver: str) -> dict[str, Any]:
        self.reserves.append({"claim_id": claim_id, "amount": amount, "approver": approver})
        return {"claim_id": claim_id, "reserve": amount}

    def issue_payment(self, claim_id: str, amount: float, approver: str) -> dict[str, Any]:
        pid = f"PAY-{len(self.payments) + 1:04d}"
        self.payments.append(
            {"payment_id": pid, "claim_id": claim_id, "amount": amount, "approver": approver}
        )
        return {"payment_id": pid, "amount": amount}

    def queue_document(self, document_id: str, reason: str) -> dict[str, Any]:
        ref = f"Q-{len(self.queue) + 1:04d}"
        self.queue.append({"ref": ref, "document_id": document_id, "reason": reason})
        return {"ref": ref}


DOCS = {
    "DOC-WATER-TX": packet(
        "HO-TX-1001",
        "Supply line under the kitchen sink burst suddenly and flooded the kitchen floor.",
        18400,
    ),
    "DOC-SEEP-TX23": packet(
        "HO-TX-1001",
        "Slow leak behind the shower wall, noticed stains after about three weeks.",
        9200,
        extra="Leak Duration Days: 21",
    ),
    "DOC-SEEP-TX19": packet(
        "HO-TX-2002",
        "Slow leak behind the shower wall, noticed stains after about three weeks.",
        9200,
        insured="Dev Patel",
        extra="Leak Duration Days: 21",
    ),
    "DOC-MOLD-TX": packet(
        "HO-TX-1001",
        "Dishwasher hose failed suddenly; water and mold in the cabinets.",
        20000,
        extra="Mold Remediation Amount: 12000",
    ),
    "DOC-MOLD-CA": packet(
        "HO-CA-3003",
        "Dishwasher hose failed suddenly; water and mold in the cabinets.",
        20000,
        insured="Lena Park",
        location="4 Bay Rd, Oakland CA",
        extra="Mold Remediation Amount: 12000",
    ),
    "DOC-BLURRY": packet("HO-TX-10~1", "Pipe burst in the laundry room.", 7000),
    "DOC-HANDWRITTEN": packet("HO-TX-1001", "Pipe burst in the laundry room.", 7000).replace(
        "Estimated Amount:", "[hw] Estimated Amount:"
    ),
    "DOC-FIRE-NEW": packet(
        "HO-TX-4004",
        "Kitchen fire started at the stove, smoke damage throughout.",
        61000,
        cause="fire",
        insured="Rick Moss",
        loss="2026-08-10",
        reported="2026-08-11",
    ),
    "DOC-LAPSED": packet(
        "HO-TX-5005", "Storm blew shingles off the roof.", 8000, cause="wind", insured="Ana Ruiz"
    ),
    "DOC-OVER-LIMIT": packet(
        "HO-TX-6006",
        "Wind storm tore off the roof and the rain ruined the upstairs.",
        55000,
        cause="wind",
        insured="Sam Cole",
    ),
    "DOC-FLOOD": packet(
        "HO-TX-1001",
        "River overflowed and surface water entered the ground floor.",
        30000,
        cause="flood",
    ),
    "DOC-NO-CAUSE": packet(
        "HO-TX-1001",
        "Someone broke the back door and stole the TV and laptop.",
        4200,
        cause="unclear ?",
    ),
    "DOC-UNKNOWN-POLICY": packet("HO-TX-9999", "Pipe burst in the laundry room.", 7000),
}


def seed_systems() -> Systems:
    return Systems(packets=dict(DOCS), policies={p["policy_number"]: dict(p) for p in POLICIES})
