"""Deterministic playbook engine: segmentation, classification fallback, expected findings,
evaluation of a draft review, guardrails and scoring."""

from __future__ import annotations

import re
from typing import Any

from contract_review.library import (
    LIBRARY,
    PROHIBITED_REDLINE,
    REQUIRED_CLAUSES,
    SEVERITY_POINTS,
    SEVERITY_RANK,
)

HEADING = re.compile(r"^(\d+)\.\s+(.+)$", re.M)


def segment(text: str) -> list[dict[str, str]]:
    heads = list(HEADING.finditer(text))
    out = []
    for i, h in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = " ".join(text[h.end() : end].split())
        out.append({"id": f"§{h.group(1)}", "heading": h.group(2).strip(), "text": body})
    return out


def keyword_type(heading: str, text: str) -> str:
    blob = f"{heading} {heading} {text}".lower()  # heading counts double
    scores = {t: sum(blob.count(k) for k in spec["keywords"]) for t, spec in LIBRARY.items()}
    best, n = max(scores.items(), key=lambda kv: kv[1])
    return best if n else "other"


def expected_findings(clauses: list[dict[str, Any]], full_text: str) -> dict[str, dict]:
    """Rule-based floor: {clause_type: {clause_id, severity, issue, evidence}}."""
    exp: dict[str, dict] = {}
    for c in clauses:
        spec = LIBRARY.get(c["type"])
        if not spec:
            continue
        for pattern, sev, issue in spec["red_flags"]:
            m = re.search(pattern, c["text"], re.I)
            if not m:
                continue
            cur = exp.get(c["type"])
            if cur is None or SEVERITY_RANK[sev] > SEVERITY_RANK[cur["severity"]]:
                exp[c["type"]] = {
                    "clause_id": c["id"],
                    "severity": sev,
                    "issue": issue,
                    "evidence": m.group(0),
                }
    present = {c["type"] for c in clauses}
    for ctype, (sev, issue) in REQUIRED_CLAUSES.items():
        applies = ctype != "data_protection" or "personal data" in full_text.lower()
        if applies and ctype not in present:
            exp[ctype] = {"clause_id": None, "severity": sev, "issue": issue, "evidence": ""}
    return exp


def evaluate(findings: list[dict], clauses: list[dict], expected: dict[str, dict]) -> list[str]:
    """Evaluator: compare a draft review with the playbook floor. Returns feedback items."""
    fb: list[str] = []
    texts = {c["id"]: c["text"] for c in clauses}
    by_type = {f["clause_type"]: f for f in findings}
    for ctype, e in expected.items():
        f = by_type.get(ctype)
        where = e["clause_id"] or "missing clause"
        if f is None:
            fb.append(f"MISSED {ctype} ({where}): {e['issue']}; severity {e['severity']}")
            continue
        if SEVERITY_RANK.get(f["severity"], 0) < SEVERITY_RANK[e["severity"]]:
            fb.append(
                f"SEVERITY {ctype}: {f['severity']} is too low, playbook says {e['severity']}"
            )
        missing_terms = [
            t
            for t in LIBRARY[ctype]["required_terms"]
            if t.lower() not in f.get("redline", "").lower()
        ]
        if missing_terms:
            fb.append(f"REDLINE {ctype}: must include {missing_terms}")
        if (
            f.get("clause_id")
            and f.get("evidence")
            and f["evidence"].lower() not in texts.get(f["clause_id"], "").lower()
        ):
            fb.append(f"EVIDENCE {ctype}: quote not found in {f['clause_id']}")
    for f in findings:
        if f["clause_type"] not in expected:
            fb.append(f"UNSUPPORTED {f['clause_type']}: no playbook red flag supports it")
    return fb


def violates_guardrail(redline: str) -> str | None:
    return next((p for p in PROHIBITED_REDLINE if re.search(p, redline, re.I)), None)


def score(findings: list[dict]) -> tuple[int, str]:
    s = sum(SEVERITY_POINTS[f["severity"]] for f in findings)
    return s, "high" if s >= 20 else "medium" if s >= 8 else "low"
