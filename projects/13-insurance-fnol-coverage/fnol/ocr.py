"""Document-Intelligence-style OCR mock for scanned FNOL packets.

A "scanned packet" is text with ``Key: Value`` lines. The mock returns field-value pairs with a
confidence per field, the way a prebuilt/custom extraction model would:

* a clean typed value -> 0.98
* a line prefixed ``[hw]`` (handwritten) -> 0.78
* a value containing smudge marks ``~`` or ``?`` -> 0.45 (marks stripped, value uncertain)
"""

from __future__ import annotations

import re
from typing import Any

MODEL_ID = "prebuilt-fnol-mock:2026-06"
KEYS = {
    "policy number": "policy_number",
    "insured name": "insured",
    "date of loss": "loss_date",
    "date reported": "reported_date",
    "loss location": "location",
    "cause of loss": "cause",
    "description": "description",
    "estimated amount": "estimate",
    "mold remediation amount": "mold_amount",
    "leak duration days": "seepage_days",
}
REQUIRED = ("policy_number", "loss_date", "estimate", "description")
MIN_CONFIDENCE = 0.85


def analyze(content: str) -> dict[str, Any]:
    fields: dict[str, dict[str, Any]] = {}
    for raw in content.splitlines():
        line, conf = raw.strip(), 0.98
        if line.startswith("[hw]"):
            line, conf = line[4:].strip(), 0.78
        m = re.match(r"([A-Za-z ]+):\s*(.*)$", line)
        if not m or m.group(1).strip().lower() not in KEYS:
            continue
        value = m.group(2).strip()
        if "~" in value or "?" in value:
            value, conf = re.sub(r"[~?]", "", value).strip(), 0.45
        fields[KEYS[m.group(1).strip().lower()]] = {"value": value, "confidence": conf}
    return {"model_id": MODEL_ID, "fields": fields, "page_count": 1}


def low_confidence(fields: dict[str, dict[str, Any]]) -> list[str]:
    """Required fields that are missing or below the confidence floor."""
    return [
        f
        for f in REQUIRED
        if f not in fields or fields[f]["confidence"] < MIN_CONFIDENCE or not fields[f]["value"]
    ]
