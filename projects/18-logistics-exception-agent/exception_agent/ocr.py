"""Document-Intelligence-style OCR mock for carrier claim documents (BOL, POD, damage report).

Text lines ``Key: Value`` become fields with a confidence: typed 0.98, handwritten ``[hw]``
0.78, smudged values (``~`` / ``?``) 0.45.
"""

from __future__ import annotations

import re
from typing import Any

MODEL_ID = "prebuilt-freight-docs-mock:2026-08"
KEYS = {
    "bol number": "bol",
    "carrier": "carrier",
    "ship date": "ship_date",
    "delivery date": "delivery_date",
    "pod exception": "pod_exception",
    "claimed amount": "amount",
    "damage description": "description",
}
REQUIRED = ("bol", "carrier", "delivery_date", "pod_exception", "amount")
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
    return {"model_id": MODEL_ID, "fields": fields}


def low_confidence(fields: dict[str, dict[str, Any]]) -> list[str]:
    return [
        f
        for f in REQUIRED
        if f not in fields or fields[f]["confidence"] < MIN_CONFIDENCE or not fields[f]["value"]
    ]
