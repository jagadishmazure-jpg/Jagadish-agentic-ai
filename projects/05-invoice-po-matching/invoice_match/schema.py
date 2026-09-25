"""Extraction schema, match exceptions and result model."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class InvoiceLine(BaseModel):
    sku: str
    description: str
    qty: float = Field(gt=0)
    unit_price: float = Field(ge=0)


class Invoice(BaseModel):
    invoice_number: str
    vendor: str
    po_number: str
    currency: str = Field(min_length=3, max_length=3)
    lines: list[InvoiceLine] = Field(min_length=1)
    subtotal: float
    tax: float = 0.0
    total: float


ExceptionCode = Literal[
    "EXTRACTION_FAILED",
    "PO_NOT_FOUND",
    "PO_CLOSED",
    "VENDOR_MISMATCH",
    "CURRENCY_MISMATCH",
    "DUPLICATE_INVOICE",
    "UNKNOWN_LINE",
    "QTY_EXCEEDS_PO",
    "QTY_EXCEEDS_RECEIPT",
    "PRICE_VARIANCE",
    "SUSPICIOUS_CONTENT",
]


class MatchException(BaseModel):
    code: ExceptionCode
    detail: str
    sku: str | None = None


class MatchResult(BaseModel):
    invoice_number: str | None
    po_number: str | None
    status: Literal["approved", "exception"]
    exceptions: list[MatchException] = Field(default_factory=list)
    extraction_attempts: int
    payment_doc: str | None = None
    exception_note: str | None = None
    route_to: str
