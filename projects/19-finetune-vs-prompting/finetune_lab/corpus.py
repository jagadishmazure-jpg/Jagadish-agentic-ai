"""Deterministic synthetic corpus of first-page OCR text for mortgage loan documents.

There is no public labelled set of loan-file documents we could ship, so this generator
stands in for "export of documents a loan processor already classified". It plants the
things a real export contains and a dataset builder has to deal with:

* **PII** (fictional names, SSNs, account numbers, emails, phones, street addresses). Every
  planted value is returned in ``Record.pii`` so tests can prove none survives scrubbing.
* **Duplicates**: the same document uploaded twice (exact) or re-scanned (whitespace/case
  changes), sometimes on a different loan.
* **Heading variety**: canonical titles, alternative wording ("Earnings Statement"), OCR-
  garbled titles, and pages with no title at all.
* **Confusers**: vocabulary shared across types (gross pay on a W-2, a pay stub and a VOE;
  "policy" on insurance and title documents).
* **OCR noise**: character-level substitutions (``l`` -> ``1``, ``rn`` -> ``m`` ...).
* **Label noise**: ~3% of documents carry the wrong label (misfiled by a processor), so no
  model can honestly reach 100% on the held-out split.

The data is synthetic; results on it demonstrate the harness and the gate, not the accuracy
any hosted model would reach on real loan files.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

FIRST = ["Avery", "Jordan", "Riley", "Casey", "Morgan", "Quinn", "Taylor", "Rowan", "Parker"]
LAST = ["Lindqvist", "Okafor", "Castellano", "Whitford", "Nakamura", "Brennan", "Delacroix"]
STREETS = ["Maple", "Harbor", "Juniper", "Summit", "Willow", "Cedar", "Lakeview"]
SUFFIX = ["St", "Ave", "Rd", "Ln", "Dr", "Blvd"]
EMPLOYERS = ["Northwind Logistics", "Contoso Health", "Fabrikam Tools", "Tailspin Air"]
BANKS = ["First Harbor Bank", "Summit Credit Union", "Lakeshore Savings"]
INSURERS = ["Evergreen Mutual", "Keystone Home Insurance", "Bluepoint Casualty"]
TITLE_COS = ["Granite Title Co", "Beacon Land Title", "Meridian Title Agency"]


@dataclass
class DocSpec:
    canonical: list[str]
    alternate: list[str]
    body: list[str]


SPECS: dict[str, DocSpec] = {
    "bank_statement": DocSpec(
        ["BANK STATEMENT", "Checking Account Statement"],
        ["Account Summary", "Monthly Activity Report", "Your Deposit Account"],
        [
            "Statement period {m1}/01 through {m1}/28",
            "Beginning balance ${amt}",
            "Ending balance ${amt}",
            "Deposits and other credits ${amt}",
            "Withdrawals and debits ${amt}",
            "Daily ledger balance",
            "ATM withdrawal at branch {n}",
            "Direct deposit payroll {emp}",
            "Overdraft protection is not enabled",
            "Interest earned this period ${small}",
            "Checks paid: #{n} #{n}",
            "Member FDIC",
        ],
    ),
    "pay_stub": DocSpec(
        ["PAY STUB", "Payroll Stub"],
        ["Earnings Statement", "Statement of Earnings and Deductions", "Direct Deposit Advice"],
        [
            "Pay period {m1}/01 - {m1}/15",
            "Pay date {m1}/20",
            "Gross pay ${amt}",
            "Net pay ${amt}",
            "Federal income tax withheld ${small}",
            "Social Security ${small} Medicare ${small}",
            "Regular hours 80.00 rate ${small}",
            "Overtime hours {n}",
            "Year to date earnings ${amt}",
            "401(k) deferral ${small}",
            "Dental pre-tax deduction ${small}",
            "Current YTD",
        ],
    ),
    "w2": DocSpec(
        ["Form W-2 Wage and Tax Statement", "W-2 WAGE AND TAX STATEMENT"],
        ["Copy B To Be Filed With Employee's FEDERAL Tax Return", "Annual Wage Report Copy C"],
        [
            "Box 1 Wages, tips, other compensation ${amt}",
            "Box 2 Federal income tax withheld ${amt}",
            "Box 3 Social security wages ${amt}",
            "Box 5 Medicare wages and tips ${amt}",
            "Employer identification number (EIN) 00-000{n}",
            "Employer's name, address, and ZIP code {emp}",
            "Box 12a code D ${small}",
            "Statutory employee Retirement plan",
            "Department of the Treasury Internal Revenue Service",
            "Tax year 2025",
        ],
    ),
    "tax_return": DocSpec(
        ["Form 1040 U.S. Individual Income Tax Return", "FORM 1040"],
        ["U.S. Return of Income 2025", "Individual Return - Department of the Treasury"],
        [
            "Filing status Married filing jointly",
            "Adjusted gross income ${amt}",
            "Taxable income ${amt}",
            "Standard deduction ${amt}",
            "Total tax ${amt}",
            "Schedule C net profit ${amt}",
            "Qualified dividends ${small}",
            "Dependents: {n}",
            "Refund amount ${small}",
            "Sign here: Under penalties of perjury",
            "Wages, salaries, tips (attach Form(s) W-2) ${amt}",
        ],
    ),
    "appraisal": DocSpec(
        ["Uniform Residential Appraisal Report", "APPRAISAL REPORT"],
        ["Property Valuation Summary", "Market Value Assessment - Form 1004"],
        [
            "Subject property {addr}",
            "Appraised value ${big}",
            "Comparable sale 1 {addr} sold ${big}",
            "Sales comparison approach",
            "Gross living area {n}00 sq ft",
            "Neighborhood: suburban, stable",
            "Condition rating C3 quality rating Q4",
            "Effective date of appraisal {m1}/12",
            "Contract price ${big}",
            "Appraiser license number {n}",
            "Site value ${big}",
        ],
    ),
    "purchase_agreement": DocSpec(
        ["Residential Purchase Agreement", "PURCHASE AND SALE AGREEMENT"],
        ["Offer to Purchase Real Estate", "Contract for Sale of Residential Property"],
        [
            "Buyer agrees to purchase and Seller agrees to sell {addr}",
            "Purchase price ${big}",
            "Earnest money deposit ${amt}",
            "Closing date on or before {m1}/30",
            "Financing contingency 21 days",
            "Inspection contingency",
            "Seller concessions ${amt}",
            "Possession at closing",
            "Buyer initials ____ Seller initials ____",
            "Counteroffer expires",
            "Escrow agent {title}",
        ],
    ),
    "homeowners_insurance": DocSpec(
        ["Homeowners Policy Declarations", "HOMEOWNERS INSURANCE DECLARATIONS PAGE"],
        ["Evidence of Property Insurance", "Your Home Coverage Summary"],
        [
            "Policy period {m1}/01/2026 to {m1}/01/2027",
            "Coverage A Dwelling ${big}",
            "Coverage B Other structures ${amt}",
            "Personal liability ${amt}",
            "All other perils deductible ${small}",
            "Mortgagee clause: lender ISAOA ATIMA",
            "Annual premium ${small}",
            "Named insured {name}",
            "Insurer {ins}",
            "Wind/hail deductible 2%",
            "Replacement cost on dwelling",
        ],
    ),
    "gift_letter": DocSpec(
        ["GIFT LETTER", "Gift Letter for Mortgage"],
        ["Letter of Gift Funds", "Donor Statement"],
        [
            "To whom it may concern",
            "I am giving a gift of ${amt} to my {rel}",
            "No repayment of this gift is expected or implied",
            "Relationship to borrower: {rel}",
            "The funds were transferred from my account at {bank}",
            "This is not a loan",
            "Donor signature ______",
            "Funds to be applied toward the purchase of {addr}",
            "I have not been paid by any party to the transaction",
        ],
    ),
    "verification_of_employment": DocSpec(
        ["Request for Verification of Employment", "VERIFICATION OF EMPLOYMENT"],
        ["Employer Confirmation of Employment", "Form 1005 Employment Check"],
        [
            "To whom it may concern",
            "Date of hire {m1}/03/2019",
            "Present position: operations analyst",
            "Base pay ${amt} per year",
            "Probability of continued employment: excellent",
            "Overtime likely to continue",
            "Employer {emp} human resources",
            "Part IV: verification of previous employment",
            "Signature of employer representative",
            "Gross earnings year to date ${amt}",
        ],
    ),
    "title_commitment": DocSpec(
        ["Commitment for Title Insurance", "TITLE COMMITMENT"],
        ["Preliminary Title Report", "Title Insurance Binder"],
        [
            "Schedule A: proposed insured {name}",
            "Schedule B Part I requirements",
            "Schedule B Part II exceptions",
            "Proposed policy amount ${big}",
            "Legal description: Lot {n}, Block {n}",
            "Vested owner of record",
            "Easements and restrictions of record",
            "Issued by {title}",
            "Payoff of existing deed of trust",
            "Effective date {m1}/05/2026",
            "ALTA owner's policy",
        ],
    ),
}

# Phrases borrowed from other document types to create realistic confusion.
CONFUSERS = [
    "Net amount ${amt}",
    "Coverage ${amt}",
    "Signature ______",
    "Effective date {m1}/01/2026",
    "Employer {emp}",
    "Transfer from {bank}",
    "Gross pay ${amt}",
    "Policy number {n}",
    "Purchase price ${big}",
    "Balance ${amt}",
    "Year to date ${amt}",
    "To whom it may concern",
    "Federal income tax ${small}",
    "Property address {addr}",
]

LABEL_NOISE = 0.03
OCR_SWAPS = [("l", "1"), ("O", "0"), ("rn", "m"), ("e", "c"), ("S", "5"), ("i", "l")]


@dataclass
class Record:
    doc_id: str
    loan_id: str
    label: str
    text: str
    pii: list[str] = field(default_factory=list)


def _ocr_noise(text: str, rng: random.Random, rate: float) -> str:
    out = text
    for a, b in OCR_SWAPS:
        pieces = out.split(a)
        if len(pieces) == 1:
            continue
        joined = pieces[0]
        for p in pieces[1:]:
            joined += (b if rng.random() < rate else a) + p
        out = joined
    return out


def _garble(title: str, rng: random.Random) -> str:
    return _ocr_noise(title.replace(" ", rng.choice(["  ", " ", "_", ""])), rng, 0.6)


def _doc(label: str, rng: random.Random) -> tuple[str, list[str]]:
    spec = SPECS[label]
    name = f"{rng.choice(FIRST)} {rng.choice(LAST)}"
    ssn = f"{rng.randint(100, 899)}-{rng.randint(10, 99)}-{rng.randint(1000, 9999)}"
    acct = str(rng.randint(10**9, 10**11))
    email = f"{name.split()[0].lower()}.{rng.randint(10, 99)}@example.com"
    phone = f"(555) 01{rng.randint(0, 9)}-{rng.randint(1000, 9999)}"
    addr = f"{rng.randint(10, 9999)} {rng.choice(STREETS)} {rng.choice(SUFFIX)}"
    slots = {
        "amt": f"{rng.randint(1, 99)},{rng.randint(100, 999)}.{rng.randint(10, 99)}",
        "small": f"{rng.randint(10, 999)}.{rng.randint(10, 99)}",
        "big": f"{rng.randint(180, 950)},{rng.randint(100, 999)}",
        "n": str(rng.randint(2, 99)),
        "m1": f"{rng.randint(1, 12):02d}",
        "emp": rng.choice(EMPLOYERS),
        "bank": rng.choice(BANKS),
        "ins": rng.choice(INSURERS),
        "title": rng.choice(TITLE_COS),
        "rel": rng.choice(["daughter", "son", "niece", "grandson"]),
        "addr": addr,
        "name": name,
    }
    roll = rng.random()
    if roll < 0.5:
        heading = rng.choice(spec.canonical)
    elif roll < 0.8:
        heading = rng.choice(spec.alternate)
    elif roll < 0.9:
        heading = _garble(rng.choice(spec.canonical), rng)
    else:
        heading = ""
    body = rng.sample(spec.body, k=rng.randint(2, 4))
    for _ in range(rng.choice([0, 1, 1, 2])):
        body.insert(rng.randint(0, len(body)), rng.choice(CONFUSERS))
    pii_lines = [
        f"Borrower: {name}",
        f"SSN {ssn}",
        f"Account {acct}",
        f"Email {email}",
        f"Phone {phone}",
        f"Address {addr}",
    ]
    chosen = rng.sample(pii_lines, k=rng.randint(2, 4))
    lines = ([heading] if heading else []) + chosen[:1] + body + chosen[1:]
    text = "\n".join(line.format(**{k: slots[k] for k in slots}) for line in lines)
    text = _ocr_noise(text, rng, rng.choice([0.0, 0.02, 0.05]))
    return text, [name, ssn, acct, email, phone, addr]


def generate(n_per_label: int = 60, n_loans: int = 150, seed: int = 19) -> list[Record]:
    """Raw export: ``n_per_label`` documents per type spread over ``n_loans`` loan files,
    plus ~6% duplicate uploads (exact or re-scanned, sometimes attached to another loan)."""
    from finetune_lab.labels import LABELS

    rng = random.Random(seed)
    records: list[Record] = []
    for label in LABELS:
        for _ in range(n_per_label):
            text, pii = _doc(label, rng)
            loan = f"LN-{rng.randint(1, n_loans):04d}"
            filed = rng.choice(LABELS) if rng.random() < LABEL_NOISE else label
            records.append(Record(f"D-{len(records) + 1:05d}", loan, filed, text, pii))
    for src in rng.sample(records, k=len(records) * 6 // 100):
        text = src.text if rng.random() < 0.5 else "  ".join(src.text.upper().split(" "))
        loan = src.loan_id if rng.random() < 0.5 else f"LN-{rng.randint(1, n_loans):04d}"
        records.append(Record(f"D-{len(records) + 1:05d}", loan, src.label, text, src.pii))
    rng.shuffle(records)
    return records
