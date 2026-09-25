"""Text-based mock invoices (as if from an email body or a text layer; no OCR needed)."""

INVOICES = {
    "clean": """INVOICE
Vendor: Acme Industrial Supply
Invoice No: INV-1001
Date: 2026-09-20
PO Number: PO-5001
Currency: USD

Item      Description                 Qty   Unit Price     Amount
BOLT-10   Hex bolt M10 (box of 100)    20        12.50     250.00
NUT-10    Hex nut M10 (box of 100)     20         8.00     160.00
WASH-10   Washer M10 (box of 200)      50        12.60     630.00

Subtotal: 1,040.00
Tax: 83.20
Total: 1,123.20
""",
    "variance": """INVOICE
Vendor: Globex Components
Invoice No: INV-2002
Date: 2026-09-21
PO Number: PO-5002
Currency: USD

Item      Description                 Qty   Unit Price     Amount
MTR-200   Servo motor 200W             10       252.00   2,520.00
CBL-5     Signal cable 5m             100         3.20     320.00
FEE-1     Expedite fee                  1        75.00      75.00

Subtotal: 2,915.00
Tax: 0.00
Total: 2,915.00
""",
    "no_po": """INVOICE
Vendor: Hooli Hardware
Invoice No: INV-3003
PO Number: PO-7777
Currency: USD

Item      Description                 Qty   Unit Price     Amount
GLV-1     Nitrile gloves (box)         10         9.00      90.00

Subtotal: 90.00
Tax: 0.00
Total: 90.00
""",
    # Messy layout: one line uses "20 x" and the price is split across columns; a strict first
    # pass misses it, validation (lines != subtotal) triggers a retry with error feedback.
    "messy": """INVOICE
Vendor: Acme Industrial Supply
Invoice No: INV-1005
PO Number: PO-5001
Currency: USD

Item      Description                 Qty   Unit Price     Amount
BOLT-10   Hex bolt M10 (box of 100)    20 x      12.50     250.00
NUT-10    Hex nut M10 (box of 100)     20         8.00     160.00

Subtotal: 410.00
Tax: 0.00
Total: 410.00
""",
}
