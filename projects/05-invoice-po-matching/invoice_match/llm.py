"""Extraction + exception-note prompts, and a deterministic regex 'LLM' for offline runs."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

from langchain_core.messages import BaseMessage

from invoice_match.schema import Invoice

EXTRACT_SYSTEM = (
    "TASK: EXTRACT attempt={attempt}\n"
    "Extract the invoice into JSON matching this schema (numbers as plain floats, no "
    "thousands separators):\n"
    + json.dumps(Invoice.model_json_schema())
    + "\n{feedback}Reply with JSON only."
)


def extract_prompt(attempt: int, feedback: str) -> str:
    # str.replace, not .format: the embedded JSON schema is full of braces
    return EXTRACT_SYSTEM.replace("{attempt}", str(attempt)).replace("{feedback}", feedback)


NOTE_SYSTEM = (
    "TASK: EXCEPTION_NOTE\n"
    "Write a concise exception note for the accounts-payable clerk: one bullet per exception "
    "(include the code and SKU), then a suggested next step (e.g. ask vendor for credit note, "
    "wait for goods receipt, ask buyer to amend PO). Plain text."
)

_HEADER = {
    "invoice_number": r"Invoice No:\s*(\S+)",
    "vendor": r"Vendor:\s*(.+)",
    "po_number": r"PO Number:\s*(\S+)",
    "currency": r"Currency:\s*([A-Z]{3})",
}
_STRICT = re.compile(
    r"^([A-Z]+-\d+)\s+(.+?)\s+(\d+(?:\.\d+)?)\s+([\d,]+\.\d{2})\s+[\d,]+\.\d{2}$", re.M
)
_LENIENT = re.compile(
    r"^([A-Z]+-\d+)\s+(.+?)\s+(\d+(?:\.\d+)?)\s*x?\s+([\d,]+\.\d{2})\s+[\d,]+\.\d{2}$", re.M
)


def _num(s: str) -> float:
    return float(s.replace(",", ""))


def regex_extract(text: str, careful: bool) -> dict:
    """Attempt 1 = strict layout; attempt 2 (after feedback) = lenient layout."""
    out: dict = {}
    for key, pat in _HEADER.items():
        m = re.search(pat, text)
        out[key] = m.group(1).strip() if m else ""
    rx = _LENIENT if careful else _STRICT
    out["lines"] = [
        {"sku": m[0], "description": m[1].strip(), "qty": _num(m[2]), "unit_price": _num(m[3])}
        for m in rx.findall(text)
    ]
    for key in ("subtotal", "tax", "total"):
        m = re.search(rf"^{key.capitalize()}:\s*([\d,]+\.\d{{2}})", text, re.M)
        out[key] = _num(m.group(1)) if m else 0.0
    return out


def mock_responder(messages: Sequence[BaseMessage]) -> str:
    system, user = str(messages[0].content), str(messages[-1].content)
    if system.startswith("TASK: EXTRACT"):
        attempt = int(re.search(r"attempt=(\d+)", system).group(1))
        return json.dumps(regex_extract(user, careful=attempt > 1))
    if system.startswith("TASK: EXCEPTION_NOTE"):
        data = json.loads(user)
        bullets = [
            f"- {e['code']}{' (' + e['sku'] + ')' if e.get('sku') else ''}: {e['detail']}"
            for e in data["exceptions"]
        ]
        codes = {e["code"] for e in data["exceptions"]}
        if "DUPLICATE_INVOICE" in codes:
            step = "Reject as a duplicate and notify the vendor; do not pay twice."
        elif codes & {"PRICE_VARIANCE", "UNKNOWN_LINE", "QTY_EXCEEDS_PO"}:
            step = "Ask the vendor for a corrected invoice or credit note for the disputed lines."
        elif "QTY_EXCEEDS_RECEIPT" in codes:
            step = "Hold payment until the remaining goods receipt is posted."
        elif codes & {"PO_NOT_FOUND", "PO_CLOSED"}:
            step = "Ask the requester/buyer for a valid open PO before processing."
        else:
            step = "Review manually."
        head = f"Invoice {data.get('invoice_number')} (PO {data.get('po_number')}) is on hold:"
        return "\n".join([head, *bullets, f"Next step: {step}"])
    return "[mock] unsupported task"
