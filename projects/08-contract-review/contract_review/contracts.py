"""Sample contract for the demo + the labeled evaluation set (loaded from evals/golden.jsonl).

Gold labels = clause types a lawyer flagged as risky, with severity. Two cases are
deliberately hard for the playbook rules (an 'evergreen' renewal phrased without "automatically
renew", and a *standard* indirect-damages exclusion that a naive rule flags), so the eval
harness shows realistic, not perfect, numbers.
"""

from __future__ import annotations

import json
from pathlib import Path

DEMO = """MASTER SERVICES AGREEMENT - Northwind Analytics ("Vendor") and Contoso Health ("Customer")
Vendor will host analytics over Customer's patient personal data.

1. Fees and Payment
Customer shall pay all invoices Net 15. Late payments accrue interest at 2% per month.

2. Term and Renewal
This Agreement shall automatically renew for successive one-year terms unless Customer gives \
notice at least 90 days before the renewal date.

3. Termination
Vendor may terminate this Agreement at any time for convenience upon 10 days' notice.

4. Limitation of Liability
Vendor's liability is capped at fees paid in the prior 3 months. Customer's liability shall be \
unlimited, including indirect and consequential damages.

5. Indemnification
Customer shall indemnify and hold harmless Vendor against any and all claims arising from use \
of the Services.

6. Confidentiality
Each party shall keep the other's Confidential Information confidential for 5 years.

7. Governing Law
This Agreement is governed by the laws of the State of New York.
"""

GOLDEN = Path(__file__).resolve().parents[1] / "evals" / "golden.jsonl"


def _load_eval_set(tag: str = "precision-recall-v1") -> list[dict]:
    """The lawyer-labelled precision/recall set lives in evals/golden.jsonl (the portfolio's
    golden-set convention); this is the original six-contract subset used by run_eval.py."""
    cases = [json.loads(line) for line in GOLDEN.read_text().splitlines() if line.strip()]
    return [
        {"id": c["id"], "text": c["input"]["text"], "gold": c["expect"]["gold"]}
        for c in cases
        if tag in c.get("tags", [])
    ]


EVAL_SET: list[dict] = _load_eval_set()
