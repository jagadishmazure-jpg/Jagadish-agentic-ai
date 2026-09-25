"""Pure functions: extraction arithmetic checks and three-way match rules."""

from __future__ import annotations

from typing import Any

from invoice_match.schema import Invoice, MatchException

PRICE_TOLERANCE_PCT = 2.0  # unit-price variance allowed vs PO
QTY_TOLERANCE = 0.0  # no over-billing on quantity
AMOUNT_EPS = 0.01


def arithmetic_errors(inv: Invoice) -> list[str]:
    errs = []
    line_sum = round(sum(ln.qty * ln.unit_price for ln in inv.lines), 2)
    if abs(line_sum - inv.subtotal) > AMOUNT_EPS:
        errs.append(
            f"sum of lines {line_sum:.2f} != subtotal {inv.subtotal:.2f} "
            "(a line may be missing or misread)"
        )
    if abs(inv.subtotal + inv.tax - inv.total) > AMOUNT_EPS:
        errs.append(f"subtotal + tax {inv.subtotal + inv.tax:.2f} != total {inv.total:.2f}")
    return errs


def three_way_match(
    inv: dict[str, Any],
    po: dict[str, Any],
    received: dict[str, float],
    already_invoiced: dict[str, float],
) -> list[MatchException]:
    out: list[MatchException] = []
    if inv["vendor"].strip().lower() != po["vendor"].strip().lower():
        out.append(
            MatchException(
                code="VENDOR_MISMATCH",
                detail=f"invoice vendor {inv['vendor']!r} != PO vendor {po['vendor']!r}",
            )
        )
    if inv["currency"] != po["currency"]:
        out.append(
            MatchException(
                code="CURRENCY_MISMATCH", detail=f"{inv['currency']} vs PO {po['currency']}"
            )
        )
    po_lines = {ln["sku"]: ln for ln in po["lines"]}
    for ln in inv["lines"]:
        sku = ln["sku"]
        pl = po_lines.get(sku)
        if pl is None:
            out.append(
                MatchException(
                    code="UNKNOWN_LINE",
                    sku=sku,
                    detail=f"{sku} ({ln['description']}) is not on the PO",
                )
            )
            continue
        billed = ln["qty"] + already_invoiced.get(sku, 0)
        if billed > pl["qty"] + QTY_TOLERANCE:
            out.append(
                MatchException(
                    code="QTY_EXCEEDS_PO",
                    sku=sku,
                    detail=f"billed {billed:g} (incl. prior invoices) > ordered {pl['qty']:g}",
                )
            )
        if billed > received.get(sku, 0) + QTY_TOLERANCE:
            out.append(
                MatchException(
                    code="QTY_EXCEEDS_RECEIPT",
                    sku=sku,
                    detail=f"billed {billed:g} (incl. prior invoices) > "
                    f"received {received.get(sku, 0):g}",
                )
            )
        var = (ln["unit_price"] - pl["unit_price"]) / pl["unit_price"] * 100
        if abs(var) > PRICE_TOLERANCE_PCT:
            out.append(
                MatchException(
                    code="PRICE_VARIANCE",
                    sku=sku,
                    detail=f"unit price {ln['unit_price']:.2f} vs PO "
                    f"{pl['unit_price']:.2f} ({var:+.1f}%, tolerance "
                    f"±{PRICE_TOLERANCE_PCT}%)",
                )
            )
    return out
