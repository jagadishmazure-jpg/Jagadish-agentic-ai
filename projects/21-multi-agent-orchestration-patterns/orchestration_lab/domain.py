"""Loan-exception domain: mock loan files, ratio math, the decision rule and the quality check.

Every orchestration pattern in this project solves the same task: an underwriter has raised an
exception ticket on a mortgage application ("DTI is over the limit, can we approve?"). Resolving
it needs four kinds of work:

* **research**   - pull the loan file, appraisal and credit summary from systems of record
* **analysis**   - compute DTI / LTV and find compensating factors
* **policy**     - retrieve the credit policy edition in force on the application date
* **drafting**   - write a cited exception memo: decision + conditions

The numbers here are the single source of truth. Agents may phrase things, but every ratio,
limit and condition is computed by code in this module (LLM proposes, code disposes).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

# ------------------------------------------------------------------------------ loan files
# All borrowers are fictional. property_value None = appraisal not received yet.
LOANS: dict[str, dict[str, Any]] = {
    "L-2101": dict(
        app_date="2026-03-02",
        amount=300_000,
        value=400_000,
        income=9_000,
        debts=4_158,
        fico=720,
        reserves=8.0,
        employment=6.0,
    ),
    "L-2102": dict(
        app_date="2026-03-05",
        amount=340_000,
        value=400_000,
        income=11_000,
        debts=4_510,
        fico=745,
        reserves=3.0,
        employment=2.0,
    ),
    "L-2103": dict(
        app_date="2026-03-09",
        amount=250_000,
        value=360_000,
        income=8_000,
        debts=4_160,
        fico=735,
        reserves=9.0,
        employment=7.0,
    ),
    "L-2104": dict(
        app_date="2026-03-11",
        amount=280_000,
        value=380_000,
        income=7_000,
        debts=3_990,
        fico=710,
        reserves=4.0,
        employment=3.0,
    ),
    "L-2105": dict(
        app_date="2026-03-16",
        amount=344_000,
        value=400_000,
        income=10_000,
        debts=4_700,
        fico=750,
        reserves=9.0,
        employment=7.0,
    ),
    "L-2106": dict(
        app_date="2026-03-18",
        amount=210_000,
        value=300_000,
        income=8_500,
        debts=3_230,
        fico=640,
        reserves=7.0,
        employment=3.0,
    ),
    "L-2107": dict(
        app_date="2026-03-20",
        amount=260_000,
        value=None,
        income=9_500,
        debts=4_370,
        fico=730,
        reserves=6.5,
        employment=5.5,
    ),
    "L-2108": dict(
        app_date="2026-03-23",
        amount=234_000,
        value=300_000,
        income=8_000,
        debts=3_600,
        fico=700,
        reserves=2.0,
        employment=2.0,
    ),
    "L-2109": dict(
        app_date="2025-11-14",
        amount=240_000,
        value=340_000,
        income=8_000,
        debts=3_920,
        fico=735,
        reserves=9.0,
        employment=8.0,
    ),
    "L-2110": dict(
        app_date="2026-03-27",
        amount=352_000,
        value=400_000,
        income=9_000,
        debts=3_960,
        fico=630,
        reserves=8.0,
        employment=9.0,
    ),
    "L-2111": dict(
        app_date="2026-03-30",
        amount=216_000,
        value=300_000,
        income=8_000,
        debts=3_880,
        fico=650,
        reserves=10.0,
        employment=8.0,
    ),
    "L-2112": dict(
        app_date="2026-04-01",
        amount=237_000,
        value=300_000,
        income=9_000,
        debts=3_600,
        fico=700,
        reserves=3.0,
        employment=4.0,
    ),
    "L-2113": dict(
        app_date="2026-04-03",
        amount=356_000,
        value=400_000,
        income=10_000,
        debts=4_600,
        fico=760,
        reserves=12.0,
        employment=10.0,
    ),
    "L-2114": dict(
        app_date="2026-04-06",
        amount=300_000,
        value=400_000,
        income=9_000,
        debts=4_158,
        fico=720,
        reserves=8.0,
        employment=6.0,
    ),
}
BORROWER_NOTES: dict[str, str] = {
    "L-2114": "Borrower letter of explanation: the car loan will be paid off at closing.",
}

# ------------------------------------------------------------------------------ policy
# Structured rule registry keyed by policy document id. Agents map retrieved evidence to a
# topic; the limits themselves always come from this table, never from model prose.
RULES: dict[str, dict[str, Any]] = {
    "CP-DTI-2025": dict(
        topic="dti",
        base=43.0,
        ceiling=48.0,
        committee=53.0,
        factors=2,
        conditions=["verify_reserves", "employment_reverification"],
    ),
    "CP-DTI-2026": dict(
        topic="dti",
        base=43.0,
        ceiling=50.0,
        committee=55.0,
        factors=2,
        conditions=["verify_reserves", "employment_reverification"],
    ),
    "CP-LTV-2026": dict(
        topic="ltv",
        base=80.0,
        ceiling=90.0,
        committee=90.0,
        factors=1,
        conditions=["mortgage_insurance"],
    ),
    "CP-FICO-2026": dict(
        topic="fico",
        base=660.0,
        ceiling=620.0,
        committee=620.0,
        factors=2,
        conditions=["no_new_credit_attestation"],
    ),
    "CP-COMP-2026": dict(
        topic="comp", reserves=6.0, fico=740.0, employment=5.0, ltv=70.0, dti=36.0
    ),
    "CP-AUTH-2026": dict(
        topic="auth", max_exceptions=2, multi_condition="senior_underwriter_signoff"
    ),
    "CP-DOCS-2026": dict(topic="docs", missing_appraisal="obtain_appraisal"),
}
TOPICS = ("dti", "ltv", "fico", "comp", "auth", "docs")
DECISIONS = ("approve", "approve_with_conditions", "decline", "pend", "escalate")
CITE = re.compile(r"\[([A-Z]+-[A-Z]+-\d{4})\]")


def topic_of(doc_id: str) -> str | None:
    rule = RULES.get(doc_id)
    return rule["topic"] if rule else None


# ------------------------------------------------------------------------------ math
def ratios(facts: dict[str, Any]) -> dict[str, float | None]:
    """DTI and LTV to one decimal; LTV is None until the appraisal arrives."""
    dti = round(facts["debts"] / facts["income"] * 100, 1)
    ltv = round(facts["amount"] / facts["value"] * 100, 1) if facts.get("value") else None
    return {"dti": dti, "ltv": ltv, "fico": float(facts["fico"])}


def metric_status(metric: str, value: float, rule: dict[str, Any]) -> str:
    """ok | exception | committee | decline for one metric against its rule."""
    if metric == "fico":  # higher is better
        if value >= rule["base"]:
            return "ok"
        return "exception" if value >= rule["ceiling"] else "decline"
    if value <= rule["base"]:
        return "ok"
    if value <= rule["ceiling"]:
        return "exception"
    return "committee" if value <= rule["committee"] else "decline"


def compensating_factors(
    facts: dict[str, Any], r: dict[str, float | None], comp: dict[str, Any], exclude: str = ""
) -> list[str]:
    """Named compensating factors present in the file (a metric never compensates itself)."""
    out = []
    if facts["reserves"] >= comp["reserves"]:
        out.append("reserves")
    if exclude != "fico" and facts["fico"] >= comp["fico"]:
        out.append("credit_score")
    if facts["employment"] >= comp["employment"]:
        out.append("employment_tenure")
    if exclude != "ltv" and r["ltv"] is not None and r["ltv"] <= comp["ltv"]:
        out.append("low_ltv")
    if exclude != "dti" and r["dti"] is not None and r["dti"] <= comp["dti"]:
        out.append("low_dti")
    return out


@dataclass
class Decision:
    decision: str
    conditions: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    exceptions: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "conditions": list(self.conditions),
            "citations": list(self.citations),
            "reasons": list(self.reasons),
            "exceptions": list(self.exceptions),
        }


def decide(facts: dict[str, Any], rules: dict[str, str]) -> Decision:
    """The credit policy as code. ``rules`` maps topic -> policy doc id in force."""
    comp = RULES[rules["comp"]]
    if not facts.get("value"):
        doc = rules["docs"]
        return Decision("pend", [RULES[doc]["missing_appraisal"]], [doc], ["appraisal missing"])
    r = ratios(facts)
    statuses = {m: metric_status(m, float(r[m]), RULES[rules[m]]) for m in ("dti", "ltv", "fico")}
    cites: list[str] = []
    for m in ("dti", "ltv", "fico"):
        if statuses[m] != "ok":
            cites.append(rules[m])
    if declined := [m for m, s in statuses.items() if s == "decline"]:
        return Decision("decline", [], cites, [f"{m} beyond exception limit" for m in declined])
    if referred := [m for m, s in statuses.items() if s == "committee"]:
        return Decision("escalate", [], cites, [f"{m} needs credit committee" for m in referred])
    exceptions = [m for m, s in statuses.items() if s == "exception"]
    if not exceptions:
        return Decision(
            "approve", [], [rules["dti"], rules["ltv"], rules["fico"]], ["within limits"]
        )
    auth = RULES[rules["auth"]]
    if len(exceptions) > auth["max_exceptions"]:
        return Decision(
            "escalate", [], [*cites, rules["auth"]], ["too many exceptions"], exceptions
        )
    conditions: list[str] = []
    for m in exceptions:
        rule = RULES[rules[m]]
        factors = compensating_factors(facts, r, comp, exclude=m)
        if len(factors) < rule["factors"]:
            return Decision(
                "decline",
                [],
                [*cites, rules["comp"]],
                [f"{m}: insufficient compensating factors"],
                exceptions,
            )
        conditions += [c for c in rule["conditions"] if c not in conditions]
    cites.append(rules["comp"])
    if len(exceptions) == 2:
        conditions.append(auth["multi_condition"])
        cites.append(rules["auth"])
    return Decision(
        "approve_with_conditions", conditions, cites, ["exception supported"], exceptions
    )


def render_memo(
    loan_id: str, facts: dict[str, Any], d: dict[str, Any], rules: dict[str, str]
) -> str:
    """Cited memo text. Every number is taken from ``ratios`` (checked by ``numbers_match``)."""
    r = ratios(facts)
    parts = [f"Exception memo {loan_id}: {d['decision'].replace('_', ' ').upper()}."]
    if r["ltv"] is None:
        parts.append(f"Appraisal not received; LTV cannot be computed [{rules['docs']}].")
    parts.append(f"DTI {r['dti']:.1f}% [{rules['dti']}].")
    if r["ltv"] is not None:
        parts.append(f"LTV {r['ltv']:.1f}% [{rules['ltv']}].")
    parts.append(f"Credit score {int(facts['fico'])} [{rules['fico']}].")
    for c in d.get("citations", []):
        if c not in (rules["dti"], rules["ltv"], rules["fico"], rules["docs"]):
            parts.append(f"See [{c}].")
    if d.get("conditions"):
        parts.append("Conditions: " + "; ".join(d["conditions"]) + ".")
    return " ".join(parts)


NUM = re.compile(r"\b(DTI|LTV) (\d+(?:\.\d)?)%")


def numbers_match(memo: str, facts: dict[str, Any]) -> bool:
    """No fabricated numbers: every DTI/LTV figure quoted in the memo equals the computed one."""
    r = ratios(facts)
    found = NUM.findall(memo)
    return bool(found) and all(r[k.lower()] == float(v) for k, v in found)


def rules_in_force(on: date) -> dict[str, str]:
    """Topic -> policy doc id in force on a date (ground truth for evals, not used by agents)."""
    dti = "CP-DTI-2025" if on < date(2026, 1, 1) else "CP-DTI-2026"
    return {
        "dti": dti,
        "ltv": "CP-LTV-2026",
        "fico": "CP-FICO-2026",
        "comp": "CP-COMP-2026",
        "auth": "CP-AUTH-2026",
        "docs": "CP-DOCS-2026",
    }


def as_of(facts: dict[str, Any]) -> date:
    return date.fromisoformat(facts["app_date"])


# ------------------------------------------------------------------------------ quality
def score(result: dict[str, Any], expect: dict[str, Any], facts: dict[str, Any] | None) -> dict:
    """Quality checks for one resolved exception (used by evals and the comparison runner)."""
    memo = result.get("memo") or ""
    cited = set(CITE.findall(memo)) | set(result.get("citations") or [])
    checks = {
        "decision": result.get("decision") == expect["decision"],
        "conditions": sorted(result.get("conditions") or [])
        == sorted(expect.get("conditions", [])),
        "citations": set(expect.get("citations", [])) <= cited and all(c in RULES for c in cited),
        "numbers": facts is not None and numbers_match(memo, facts),
        "completed": result.get("stop_reason") == "completed",
    }
    return {"passed": all(checks.values()), "checks": checks}


# ------------------------------------------------------------------------------ tickets
def ticket(loan_id: str) -> dict[str, Any]:
    """The exception ticket an underwriter raised (mock ticket queue)."""
    f = LOANS[loan_id]
    return {
        "loan_id": loan_id,
        "app_date": f["app_date"],
        "text": f"Exception review requested for {loan_id} (application {f['app_date']}).",
    }
