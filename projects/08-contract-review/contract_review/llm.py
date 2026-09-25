"""Clause classification + review (optimizer) prompts, and deterministic mocks.

The mock reviewer behaves like a plausible first-pass LLM: it spots red flags but rates
everything 'medium', writes a generic redline and forgets missing clauses; on revision it
follows the evaluator's feedback."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

from langchain_core.messages import BaseMessage

from contract_review.library import LIBRARY
from contract_review.rules import keyword_type

TYPES = [*LIBRARY, "other"]
CLASSIFY_SYSTEM = (
    "TASK: CLASSIFY\nClassify the contract clause into one type: "
    + ", ".join(TYPES)
    + ". Reply with the type only."
)
REVIEW_SYSTEM = (
    "TASK: REVIEW\n"
    "You review contract clauses against the company playbook (provided). Return JSON: "
    '{"findings": [{"clause_id": "§4" or null, "clause_type": str, "severity": '
    '"low|medium|high|critical", "issue": str, "evidence": "exact quote from the clause", '
    '"redline": "proposed replacement text"}]}. Only flag real deviations from the playbook. '
    "If evaluator feedback is present, address every item."
)


def mock_review(payload: dict) -> str:
    feedback: list[str] = payload.get("feedback", [])
    if payload.get("previous_findings"):  # revise the previous draft, don't start over
        findings = [dict(f) for f in payload["previous_findings"]]
        clauses: list[dict] = []
    else:
        findings, clauses = [], payload["clauses"]
    for c in clauses:
        spec = LIBRARY.get(c["type"])
        if not spec:
            continue
        for pattern, _sev, issue in spec["red_flags"]:
            m = re.search(pattern, c["text"], re.I)
            if m:
                findings.append(
                    {
                        "clause_id": c["id"],
                        "clause_type": c["type"],
                        "severity": "medium",
                        "issue": issue,
                        "evidence": m.group(0),
                        "redline": "Revise to align with the company standard.",
                    }
                )
                break
    by_type = {f["clause_type"]: f for f in findings}
    for item in feedback:
        kind, ctype = item.split(" ", 2)[:2]
        ctype = ctype.rstrip(":")
        sev = re.search(r"(?:severity|says) (low|medium|high|critical)", item)
        if kind == "MISSED":
            by_type[ctype] = {
                "clause_id": None
                if "missing clause" in item
                else re.search(r"\((§\d+)", item).group(1),
                "clause_type": ctype,
                "severity": sev.group(1),
                "issue": item.split(": ", 1)[1].split(";")[0],
                "evidence": "",
                "redline": LIBRARY[ctype]["redline"],
            }
        elif kind == "SEVERITY" and ctype in by_type:
            by_type[ctype]["severity"] = sev.group(1)
        elif kind == "REDLINE" and ctype in by_type:
            by_type[ctype]["redline"] = LIBRARY[ctype]["redline"]
        elif kind == "UNSUPPORTED":
            by_type.pop(ctype, None)
    return json.dumps({"findings": list(by_type.values())})


def mock_responder(messages: Sequence[BaseMessage]) -> str:
    system, user = str(messages[0].content), str(messages[-1].content)
    if system.startswith("TASK: CLASSIFY"):
        heading, _, text = user.partition("\n")
        return keyword_type(heading, text)
    if system.startswith("TASK: REVIEW"):
        return mock_review(json.loads(user))
    return "[mock] unsupported task"
