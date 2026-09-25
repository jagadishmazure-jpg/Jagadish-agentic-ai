"""Sample contract for the demo + a small labeled evaluation set.

Gold labels = clause types a lawyer flagged as risky, with severity. Two cases are
deliberately hard for the playbook rules (an 'evergreen' renewal phrased without "automatically
renew", and a *standard* indirect-damages exclusion that a naive rule flags), so the eval
harness shows realistic, not perfect, numbers.
"""

from __future__ import annotations

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

EVAL_SET: list[dict] = [
    {
        "id": "EV1-demo-msa",
        "text": DEMO,
        "gold": {
            "payment_terms": "medium",
            "auto_renewal": "medium",
            "termination": "high",
            "limitation_of_liability": "critical",
            "indemnification": "high",
            "data_protection": "high",
        },
    },
    {
        "id": "EV2-balanced",
        "text": """SERVICES AGREEMENT
Vendor processes Customer personal data as processor.

1. Payment
Invoices are payable Net 45; late amounts accrue 1% per month.

2. Renewal
The agreement renews for one-year terms unless either party gives 30 days' written notice.

3. Termination
Either party may terminate for material breach not cured within 30 days.

4. Liability
Each party's liability is capped at fees paid in the prior 12 months. Neither party is liable \
for indirect or consequential damages.

5. Data Protection
Vendor shall notify Customer of a personal data breach within 72 hours under the DPA.

6. Governing Law
This Agreement is governed by the laws of the State of New York.
""",
        "gold": {},
    },
    {
        "id": "EV3-evergreen",
        "text": """SUBSCRIPTION TERMS
Vendor stores Customer personal data.

1. Term
This subscription is evergreen and continues year to year unless cancelled 120 days prior to \
the anniversary date.

2. Liability
Customer's liability for breach of these terms is without limit.

3. Data Protection
Vendor will notify Customer of security incidents within 30 days.
""",
        "gold": {
            "auto_renewal": "medium",
            "limitation_of_liability": "critical",
            "data_protection": "high",
        },
    },
    {
        "id": "EV4-supplier",
        "text": """SUPPLY AGREEMENT

1. Payment Terms
Late invoices bear interest at 3% per month.

2. Termination
Supplier may terminate for convenience with 5 days' notice.

3. Liability
Each party's liability is capped at fees paid in the prior 12 months.
""",
        "gold": {"payment_terms": "medium", "termination": "high"},
    },
    {
        "id": "EV5-nda",
        "text": """MUTUAL NDA

1. Confidentiality
Each party shall protect the other's Confidential Information for 3 years.

2. Liability
Neither party's liability under this NDA shall exceed $1,000,000.

3. Governing Law
This NDA is governed by the laws of Delaware.
""",
        "gold": {},
    },
    {
        "id": "EV6-indemnity",
        "text": """PLATFORM TERMS
The platform processes end-user personal data on Customer's behalf.

1. Indemnity
Customer shall indemnify Provider against all claims, losses and fees of any kind.

2. Liability
Each party's liability is capped at fees paid in the prior 12 months.

3. Governing Law
These terms are governed by the laws of England.
""",
        "gold": {"indemnification": "high", "data_protection": "high"},
    },
]
