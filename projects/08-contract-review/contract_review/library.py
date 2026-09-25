"""Clause library (legal playbook): classification keywords, red flags with severity,
standard position and approved redline language."""

from __future__ import annotations

SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}
SEVERITY_POINTS = {"low": 1, "medium": 3, "high": 6, "critical": 10}

LIBRARY: dict[str, dict] = {
    "limitation_of_liability": {
        "keywords": ("liability", "liable", "damages"),
        "standard": "Each party's liability is capped at the fees paid in the prior 12 months; "
        "no indirect damages.",
        "red_flags": [
            (
                r"unlimited liability|liability (?:shall be |is )?unlimited|without (?:any )?limit",
                "critical",
                "Uncapped liability for the customer",
            ),
            (
                r"indirect|consequential",
                "high",
                "Customer liable for indirect/consequential damages",
            ),
        ],
        "redline": "Each party's aggregate liability shall not exceed the fees paid in the "
        "12 months preceding the claim; neither party is liable for indirect or "
        "consequential damages.",
        "required_terms": ("12 months", "indirect"),
    },
    "indemnification": {
        "keywords": ("indemnify", "indemnification", "hold harmless"),
        "standard": "Mutual indemnity limited to third-party IP claims and gross negligence.",
        "red_flags": [
            (
                r"customer shall indemnify.{0,80}(?:any and all|all claims)",
                "high",
                "One-sided, unlimited customer indemnity",
            ),
        ],
        "redline": "Each party shall indemnify the other against third-party claims arising "
        "from its gross negligence, wilful misconduct or IP infringement.",
        "required_terms": ("each party", "third-party"),
    },
    "auto_renewal": {
        "keywords": ("renew", "renewal", "evergreen"),
        "standard": "Renewal requires written notice; either party may opt out with 30 days' "
        "notice.",
        "red_flags": [
            (
                r"automatically renew.{0,120}(?:90|120|180) days",
                "medium",
                "Auto-renewal with a long opt-out notice period",
            ),
        ],
        "redline": "The agreement renews for successive one-year terms unless either party "
        "gives 30 days' written notice of non-renewal.",
        "required_terms": ("30 days",),
    },
    "termination": {
        "keywords": ("terminate", "termination"),
        "standard": "Either party may terminate for material breach uncured after 30 days.",
        "red_flags": [
            (
                r"(?:vendor|supplier|provider) may terminate.{0,40}(?:at any time|for convenience)",
                "high",
                "Vendor can terminate for convenience; customer cannot",
            ),
        ],
        "redline": "Either party may terminate for material breach not cured within 30 days "
        "of written notice.",
        "required_terms": ("either party", "30 days"),
    },
    "payment_terms": {
        "keywords": ("payment", "invoice", "fees", "late"),
        "standard": "Net 45; late interest capped at 1% per month.",
        "red_flags": [
            (
                r"(?:[2-9]|1\d)(?:\.\d+)?% per month",
                "medium",
                "Late-payment interest above 1%/month",
            ),
            (r"net (?:7|10|15)\b", "low", "Payment term shorter than Net 30"),
        ],
        "redline": "Invoices are payable Net 45; late amounts accrue interest of at most 1% "
        "per month.",
        "required_terms": ("Net 45", "1% per month"),
    },
    "data_protection": {
        "keywords": ("personal data", "gdpr", "data protection", "processor"),
        "standard": "Vendor acts as processor under a DPA; breach notice within 72 hours.",
        "red_flags": [
            (
                r"notify.{0,60}(?:within )?(?:30|60|90) days|without undue delay is not required",
                "high",
                "Breach notification slower than 72 hours",
            ),
        ],
        "redline": "Vendor shall notify Customer of any personal data breach within 72 hours "
        "and process personal data only under the attached DPA.",
        "required_terms": ("72 hours", "DPA"),
    },
    "governing_law": {
        "keywords": ("governed by", "governing law", "jurisdiction"),
        "standard": "Laws of the State of New York; courts of New York County.",
        "red_flags": [],
        "redline": "",
        "required_terms": (),
    },
    "confidentiality": {
        "keywords": ("confidential",),
        "standard": "Mutual confidentiality for 5 years.",
        "red_flags": [],
        "redline": "",
        "required_terms": (),
    },
}

REQUIRED_CLAUSES = {
    "data_protection": (
        "high",
        "No data protection / DPA clause although personal data is processed",
    ),
    "limitation_of_liability": ("critical", "No limitation of liability clause"),
}

# guardrail: redlines must never propose giving these away
PROHIBITED_REDLINE = (
    r"waive all",
    r"unlimited liability",
    r"no liability for vendor",
    r"customer shall indemnify.{0,40}any and all",
)
DISCLAIMER = (
    "AI-assisted first-pass review against the company playbook. Not legal advice; "
    "a lawyer must approve before any redline is sent."
)
